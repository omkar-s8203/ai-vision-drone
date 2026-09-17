import json

import numpy as np
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription

from companion.comms.protocol import MessageType, make_envelope
from companion.comms.video_pipeline import AiortcVideoPipeline
from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport, wait_until
from companion.tests.test_video_pipeline import _wait_ice_complete
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.detector import PassthroughDetector


@pytest.mark.asyncio
async def test_orchestrator_routes_webrtc_offer_through_to_a_real_answer(tmp_path):
    """Proves the wiring in CompanionOrchestrator (on_webrtc_offer ->
    AiortcVideoPipeline.handle_offer -> send_webrtc_answer) actually works
    end-to-end through the comms layer, not just the pipeline in isolation
    (see test_video_pipeline.py) or the message routing in isolation (see
    test_ws_server.py)."""
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")

    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    transport = FakeTransport(connected=True)
    link = GroundStationLink(transport)
    recorder = SessionRecorder(tmp_path)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    video_pipeline = AiortcVideoPipeline(frame_source=lambda: frame, fps=10)

    orchestrator = CompanionOrchestrator(
        camera=None,
        detector=PassthroughDetector(),
        tracker=IouKalmanTracker(),
        distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
        follow_controller=FollowController(follow_cfg),
        orbit_controller=OrbitController(orbit_cfg),
        approach_controller=ApproachTestController(approach_cfg),
        mavlink=MavlinkBridge("udpin:127.0.0.1:14670"),
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
        video_pipeline=video_pipeline,
    )

    client_pc = RTCPeerConnection()
    client_pc.addTransceiver("video", direction="recvonly")
    offer = await client_pc.createOffer()
    await client_pc.setLocalDescription(offer)
    await _wait_ice_complete(client_pc)

    envelope = make_envelope(
        MessageType.WEBRTC_OFFER,
        {"sdp": client_pc.localDescription.sdp, "sdp_type": client_pc.localDescription.type},
        seq=1,
    )
    transport.inject(envelope.to_json())

    # Real ICE gathering over UDP (even on loopback) is slow and somewhat
    # unpredictable in a sandboxed environment, hence the generous timeout -
    # this is genuinely waiting on network/OS behavior, not polling for a
    # fixed short-lived condition.
    await wait_until(lambda: len(transport.sent) > 0, timeout=15.0)
    sent_envelope = json.loads(transport.sent[0])
    assert sent_envelope["type"] == MessageType.WEBRTC_ANSWER
    assert "sdp" in sent_envelope["payload"]

    # Applying the answer must not raise - full ICE/DTLS completion is not
    # asserted here since that depends on real connectivity/NAT behavior
    # this sandboxed environment cannot guarantee.
    await client_pc.setRemoteDescription(
        RTCSessionDescription(
            sdp=sent_envelope["payload"]["sdp"], type=sent_envelope["payload"]["sdp_type"]
        )
    )

    await client_pc.close()
    await video_pipeline.stop()
    recorder.close()
