import asyncio

import numpy as np
import pytest

from companion.comms.video_pipeline import AiortcVideoPipeline, overlay_latency_timestamp


def test_overlay_latency_timestamp_does_not_mutate_the_input_frame():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    stamped = overlay_latency_timestamp(frame)
    assert np.array_equal(frame, np.zeros((100, 200, 3), dtype=np.uint8))
    assert stamped.shape == frame.shape
    assert stamped.any()  # the burned-in text changed some pixels


def test_wrap_frame_source_with_latency_overlay_stamps_each_frame():
    from companion.main import wrap_frame_source_with_latency_overlay

    calls = [np.zeros((100, 200, 3), dtype=np.uint8)]
    wrapped = wrap_frame_source_with_latency_overlay(lambda: calls[0])
    stamped = wrapped()
    assert stamped.any()


def test_wrap_frame_source_with_latency_overlay_passes_through_none():
    from companion.main import wrap_frame_source_with_latency_overlay

    wrapped = wrap_frame_source_with_latency_overlay(lambda: None)
    assert wrapped() is None


aiortc = pytest.importorskip("aiortc")
from aiortc import RTCPeerConnection, RTCSessionDescription  # noqa: E402


async def _wait_ice_complete(pc) -> None:
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def _on_change():
        if pc.iceGatheringState == "complete":
            done.set()

    await asyncio.wait_for(done.wait(), timeout=5.0)


@pytest.mark.asyncio
async def test_aiortc_pipeline_streams_video_to_a_real_peer():
    """Exercises the real production AiortcVideoPipeline end-to-end against
    a genuine aiortc peer (standing in for the Android WebRTC client) over
    loopback - no camera, no Android, no network beyond localhost. Confirms
    the offer/answer handling in companion/comms/video_pipeline.py actually
    produces a working media connection, not just importable code."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    pipeline = AiortcVideoPipeline(frame_source=lambda: frame, fps=10)

    client_pc = RTCPeerConnection()
    client_pc.addTransceiver("video", direction="recvonly")

    received_track = {}

    @client_pc.on("track")
    def _on_track(track):
        received_track["track"] = track

    offer = await client_pc.createOffer()
    await client_pc.setLocalDescription(offer)
    await _wait_ice_complete(client_pc)

    answer_sdp, answer_type = await pipeline.handle_offer(
        client_pc.localDescription.sdp, client_pc.localDescription.type
    )
    await client_pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type=answer_type))

    for _ in range(50):
        if "track" in received_track:
            break
        await asyncio.sleep(0.1)
    assert "track" in received_track, "client never received the remote video track"

    video_frame = await asyncio.wait_for(received_track["track"].recv(), timeout=5.0)
    assert video_frame.width == 640
    assert video_frame.height == 480

    await client_pc.close()
    await pipeline.stop()
