from __future__ import annotations

import asyncio
from typing import Callable, Optional

import numpy as np


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
    encode on the Pi 5, for lower latency than the pure-Python aiortc path.
    Not implemented yet - planned once AiortcVideoPipeline has proven the
    signaling/control flow end-to-end (docs plan M5).
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "GstreamerVideoPipeline is planned after the aiortc pipeline is validated - "
            "see docs plan M5."
        )

    async def handle_offer(self, sdp: str, sdp_type: str) -> tuple[str, str]:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
