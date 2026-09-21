import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachState, ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.camera import Frame
from companion.vision.detector import BBox, Detection, PassthroughDetector


def _build_minimal_orchestrator(tmp_path):
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path)
    orchestrator = CompanionOrchestrator(
        camera=None,
        detector=PassthroughDetector(),
        tracker=IouKalmanTracker(),
        distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
        follow_controller=FollowController(follow_cfg),
        orbit_controller=OrbitController(orbit_cfg),
        approach_controller=ApproachTestController(approach_cfg),
        mavlink=MavlinkBridge("udpin:127.0.0.1:14740"),
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
    )
    return orchestrator, recorder


@pytest.mark.asyncio
async def test_real_fence_breach_telemetry_aborts_an_active_approach(tmp_path):
    """Proves the actual wiring, not just that ApproachTestController can
    react to a hand-constructed geofence_breached=True (already covered by
    test_approach_test.py::test_geofence_breach_aborts) - this simulates
    what a real MavlinkBridge.telemetry.fence_breached=True (from a real
    SYS_STATUS message, see test_mock_fc.py) actually does once it reaches
    process_frame(). Before this test/fix, main.py hardcoded
    geofence_breached=False here regardless of telemetry."""
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    # Without these, the Supervisor's own stale-subsystem/fc-mode gates
    # would force SAFE before process_frame() ever reaches the APPROACHING
    # branch at all, and the test would "pass" for the wrong reason (the
    # approach controller never even seeing the geofence input, not
    # correctly rejecting it).
    orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
    orchestrator.watchdog.beat("mavlink")
    orchestrator.watchdog.beat("rc_channels")
    person = Detection(bbox=BBox(600, 300, 80, 160), score=0.9, class_id=0, class_name="person", frame_ts=0.0)

    orchestrator._on_target_selected({"x": 640.0, "y": 380.0, "point": True})
    await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[person]))
    orchestrator._on_mode_command({"mode": "approach"})
    assert orchestrator.approach.state == ApproachState.APPROACHING

    orchestrator.mavlink.telemetry.fence_breached = True
    await orchestrator.process_frame(Frame(ts=0.1, width=1280, height=720, raw_detection_output=[person]))

    assert orchestrator.approach.state == ApproachState.ABORTED
    recorder.close()


@pytest.mark.asyncio
async def test_no_fence_breach_leaves_approach_running(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator.mavlink.connect()  # unlike the abort path, this one actually sends a real setpoint
    orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
    orchestrator.watchdog.beat("mavlink")
    orchestrator.watchdog.beat("rc_channels")
    person = Detection(bbox=BBox(600, 300, 80, 160), score=0.9, class_id=0, class_name="person", frame_ts=0.0)

    orchestrator._on_target_selected({"x": 640.0, "y": 380.0, "point": True})
    await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[person]))
    orchestrator._on_mode_command({"mode": "approach"})

    assert orchestrator.mavlink.telemetry.fence_breached is False
    await orchestrator.process_frame(Frame(ts=0.1, width=1280, height=720, raw_detection_output=[person]))

    assert orchestrator.approach.state == ApproachState.APPROACHING
    recorder.close()
