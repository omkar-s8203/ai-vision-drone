from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

import cv2
import numpy as np


def overlay_latency_timestamp(frame: np.ndarray) -> np.ndarray:
    """Burns the current wall-clock time (ms precision) into a frame's
    corner - for docs plan M5's own suggested glass-to-glass latency test
    method: read this timestamp off the Android-rendered frame (e.g. by
    pausing on a screen recording) and compare it against wall-clock time
    at the moment of capture, given both devices' clocks are reasonably
    synced (NTP/chrony). Not wired in by default - see
    `companion.main.wrap_frame_source_with_latency_overlay`.
    """
    out = frame.copy()
    cv2.putText(
        out, f"{time.time():.3f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA
    )
    return out


class VideoPipeline:
    async def handle_offer(self, sdp: str, sdp_type: str) -> tuple[str, str]:
        """Given a WebRTC offer's SDP, returns (answer_sdp, answer_type)."""
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError


class AiortcVideoPipeline(VideoPipeline):
    """Quick-bringup WebRTC video pipeline using aiortc (pure Python).
    Intended as the early-development path; GstreamerVideoPipeline replaces
    this once the signaling/control flow is functionally proven, for lower
    latency via hardware H.264 encode (docs plan M5).
    """

    def __init__(self, frame_source: Callable[[], Optional[np.ndarray]], fps: int = 20) -> None:
        try:
            from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack  # type: ignore
            from av import VideoFrame  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "aiortc (and av) is not installed - install the 'video' optional "
                "dependency group to use AiortcVideoPipeline."
            ) from exc

        self._RTCPeerConnection = RTCPeerConnection
        self._RTCSessionDescription = RTCSessionDescription
        self._VideoFrame = VideoFrame
        self.frame_source = frame_source
        self.fps = fps
        self._pcs: set = set()

        outer = self

        class CameraStreamTrack(VideoStreamTrack):
            async def recv(self):
                pts, time_base = await self.next_timestamp()
                array = outer.frame_source()
                if array is None:
                    array = np.zeros((480, 640, 3), dtype=np.uint8)
                frame = outer._VideoFrame.from_ndarray(array, format="bgr24")
                frame.pts = pts
                frame.time_base = time_base
                return frame

        self._track_cls = CameraStreamTrack

    async def handle_offer(self, sdp: str, sdp_type: str) -> tuple[str, str]:
        pc = self._RTCPeerConnection()
        self._pcs.add(pc)
        pc.addTrack(self._track_cls())

        @pc.on("connectionstatechange")
        async def on_state_change():
            if pc.connectionState in ("failed", "closed"):
                self._pcs.discard(pc)

        offer = self._RTCSessionDescription(sdp=sdp, type=sdp_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return pc.localDescription.sdp, pc.localDescription.type

    async def stop(self) -> None:
        await asyncio.gather(*(pc.close() for pc in self._pcs), return_exceptions=True)
        self._pcs.clear()


class GstreamerVideoPipeline(VideoPipeline):
    """Production video path: GStreamer webrtcbin + v4l2h264enc hardware
    encode on the Pi 5, for lower latency than the pure-Python aiortc path
    (docs plan M5) - AiortcVideoPipeline has since proven the signaling/
    control flow end-to-end on real hardware, so this fills in the
    previously-deferred hardware-encode path.

    **UNVERIFIED - genuinely, not just "not yet run on real hardware" the
    way this project usually flags things.** PyGObject + GStreamer (with
    its webrtc/sdp plugins) aren't installed on this dev machine, so unlike
    every other module in this project, this code has never even been
    successfully imported, let alone exercised - there is no test for it,
    not even one that would only run on a real Pi (contrast
    AiortcVideoPipeline's own tests, which use `pytest.importorskip
    ("aiortc")` and so at least run for real wherever aiortc is present).
    The overall shape (parse-launch a pipeline string, set-remote-
    description -> create-answer -> set-local-description on webrtcbin,
    wait for ICE gathering to fully complete before returning the answer's
    SDP) matches the standard, widely-documented GStreamer webrtcbin
    pattern, and the non-trickle-ICE assumption (wait for gathering to
    finish rather than exchanging candidates as a separate message) matches
    what AiortcVideoPipeline already assumes - this project's protocol
    (`docs/protocol.md`) has no message type for trickled ICE candidates at
    all. Treat this as a first draft to validate on the actual Pi, not a
    finished, trustworthy implementation - if it does not work, that is
    expected, not a regression.
    """

    def __init__(
        self,
        video_device: str = "/dev/video0",
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        bitrate_kbps: int = 2000,
    ) -> None:
        try:
            import gi

            gi.require_version("Gst", "1.0")
            gi.require_version("GstWebRTC", "1.0")
            gi.require_version("GstSdp", "1.0")
            from gi.repository import Gst, GstSdp, GstWebRTC  # type: ignore
        except (ImportError, ValueError) as exc:
            raise RuntimeError(
                "PyGObject + GStreamer (with its webrtc/sdp plugins) are not installed - "
                "this is the Pi's hardware-encode video path (docs plan M5); use "
                "AiortcVideoPipeline (the confirmed-working software-encode path) instead "
                "until this one is actually validated on real hardware."
            ) from exc

        Gst.init(None)
        self._Gst = Gst
        self._GstWebRTC = GstWebRTC
        self._GstSdp = GstSdp
        self._pipelines: list = []

        bitrate_bps = bitrate_kbps * 1000
        self._pipeline_str = (
            f"v4l2src device={video_device} ! "
            f"video/x-raw,width={width},height={height},framerate={fps}/1 ! "
            f'v4l2h264enc extra-controls="controls,video_bitrate={bitrate_bps}" ! '
            "h264parse ! rtph264pay config-interval=1 pt=96 ! "
            "webrtcbin name=sendrecv bundle-policy=max-bundle"
        )

    async def handle_offer(self, sdp: str, sdp_type: str) -> tuple[str, str]:
        Gst = self._Gst
        GstWebRTC = self._GstWebRTC
        GstSdp = self._GstSdp

        pipeline = Gst.parse_launch(self._pipeline_str)
        webrtc = pipeline.get_by_name("sendrecv")
        self._pipelines.append(pipeline)

        loop = asyncio.get_event_loop()
        answer_future: asyncio.Future = loop.create_future()

        ok, sdpmsg = GstSdp.SDPMessage.new()
        GstSdp.sdp_message_parse_buffer(sdp.encode("utf-8"), sdpmsg)
        offer_desc = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sdpmsg)

        def on_ice_gathering_complete_extract_answer() -> None:
            # Non-trickle ICE (see class docstring): webrtcbin bakes
            # candidates into local_description's SDP as they gather, so
            # waiting for gathering to finish before reading it back gives
            # a complete, self-contained answer - no separate ICE-candidate
            # message needed, matching AiortcVideoPipeline's own assumption
            # and this project's protocol (docs/protocol.md).
            local_desc = webrtc.props.local_description
            answer_sdp_text = local_desc.sdp.as_text()
            loop.call_soon_threadsafe(answer_future.set_result, (answer_sdp_text, "answer"))

        def on_ice_gathering_state_notify(_element, _pspec) -> None:
            if webrtc.props.ice_gathering_state == GstWebRTC.WebRTCICEGatheringState.COMPLETE:
                on_ice_gathering_complete_extract_answer()

        def on_answer_created(promise) -> None:
            promise.wait()
            reply = promise.get_reply()
            answer = reply.get_value("answer")
            webrtc.emit("set-local-description", answer, Gst.Promise.new())
            webrtc.connect("notify::ice-gathering-state", on_ice_gathering_state_notify)

        def on_remote_description_set(promise) -> None:
            promise.wait()
            answer_promise = Gst.Promise.new_with_change_func(lambda p: on_answer_created(p), None)
            webrtc.emit("create-answer", None, answer_promise)

        set_remote_promise = Gst.Promise.new_with_change_func(lambda p: on_remote_description_set(p), None)
        webrtc.emit("set-remote-description", offer_desc, set_remote_promise)

        pipeline.set_state(Gst.State.PLAYING)
        return await answer_future

    async def stop(self) -> None:
        for pipeline in self._pipelines:
            pipeline.set_state(self._Gst.State.NULL)
        self._pipelines.clear()
