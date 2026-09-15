import asyncio

import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport, wait_until
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
from companion.vision.camera import Frame
from companion.vision.detector import PassthroughDetector
from sim.mock_fc import MockFlightController
from sim.synthetic_target import SyntheticTargetGenerator

TEST_FC_PORT = 14650
TEST_BRIDGE_PORT = 14651


@pytest.mark.asyncio
async def test_follow_mode_sends_setpoints_then_rc_override_halts_them(tmp_path):
    """End-to-end: synthetic target -> selection -> tracking -> follow
    guidance -> MAVLink bridge -> mock flight controller, then verifies the
    pilot's RC override immediately and unconditionally halts guidance
    output, per the project's non-negotiable safety requirement."""
    follow_cfg = load_yaml("follow_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")

    mock_fc = MockFlightController(f"udpin:127.0.0.1:{TEST_FC_PORT}")
    mock_fc.set_mode("GUIDED")
    mock_fc.set_armed(True)
    fc_task = asyncio.create_task(mock_fc.run(rate_hz=20.0))

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{TEST_BRIDGE_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", TEST_FC_PORT)
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    mavlink_task = asyncio.create_task(
        mavlink.run(on_message=lambda _msg: watchdog.beat("mavlink"))
    )

    generator = SyntheticTargetGenerator(image_width=1280, image_height=720, path_amplitude_px=0.0)
    transport = FakeTransport(connected=True)
    link = GroundStationLink(transport)
    recorder = SessionRecorder(tmp_path)

    orchestrator = CompanionOrchestrator(
        camera=None,
        detector=PassthroughDetector(),
        tracker=IouKalmanTracker(),
        distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
        follow_controller=FollowController(follow_cfg),
        approach_controller=ApproachTestController(approach_cfg),
        mavlink=mavlink,
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
    )

    try:
        await wait_until(lambda: mavlink.telemetry.fc_mode == "GUIDED", timeout=3.0)
        watchdog.beat("camera")
        watchdog.beat("tracker")

        initial_bbox = generator.detections_at(0.0)[0].bbox
        orchestrator._on_target_selected(
            {"x": initial_bbox.x, "y": initial_bbox.y, "w": initial_bbox.w, "h": initial_bbox.h}
        )
        orchestrator._on_mode_command({"mode": "follow"})

        ts = 0.0
        last_result = None
        for _ in range(5):
            watchdog.beat("camera")
            watchdog.beat("tracker")
            frame = Frame(
                ts=ts, width=1280, height=720, raw_detection_output=generator.detections_at(ts)
            )
            last_result = await orchestrator.process_frame(frame)
            ts += 0.1
            await asyncio.sleep(0.05)

        assert orchestrator.state_machine.state == TrackingState.TRACKING
        assert last_result["supervisor_decision"].guidance_allowed is True
        await wait_until(lambda: len(mock_fc.received_setpoints) > 0, timeout=2.0)

        mock_fc.set_rc_override(True)
        await wait_until(
            lambda: RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]).is_overriding(
                mavlink.telemetry.rc_channels
            ),
            timeout=2.0,
        )

        watchdog.beat("camera")
        watchdog.beat("tracker")
        frame = Frame(ts=ts, width=1280, height=720, raw_detection_output=generator.detections_at(ts))
        result = await orchestrator.process_frame(frame)

        assert result["supervisor_decision"].guidance_allowed is False
        assert result["supervisor_decision"].reason == "rc_override"
        assert result["command_sent"] is False
    finally:
        fc_task.cancel()
        mavlink_task.cancel()
        recorder.close()
        await asyncio.gather(fc_task, mavlink_task, return_exceptions=True)
