import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.guidance.smart_shot import ShotType, SmartShotController, SmartShotState
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor, SupervisorState
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
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
        mavlink=MavlinkBridge("udpin:127.0.0.1:14700"),
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
    )
    return orchestrator, recorder


def test_dronie_mode_command_starts_the_shot(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)

    orchestrator._on_mode_command({"mode": "dronie"})

    assert orchestrator.requested_mode == SupervisorState.SMART_SHOT
    assert orchestrator.smart_shot.is_active is True
    assert orchestrator.smart_shot.shot_type == ShotType.DRONIE
    recorder.close()


def test_parabola_mode_command_starts_the_shot(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)

    orchestrator._on_mode_command({"mode": "parabola"})

    assert orchestrator.smart_shot.shot_type == ShotType.PARABOLA
    recorder.close()


def test_switching_to_a_different_mode_stops_an_active_shot(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator._on_mode_command({"mode": "dronie"})

    orchestrator._on_mode_command({"mode": "idle"})

    assert orchestrator.smart_shot.is_active is False
    recorder.close()


def test_abort_stops_an_active_shot(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator._on_mode_command({"mode": "dronie"})

    orchestrator._on_abort({"reason": "operator"})

    assert orchestrator.smart_shot.is_active is False
    assert orchestrator.requested_mode == SupervisorState.IDLE
    recorder.close()


@pytest.mark.asyncio
async def test_smart_shot_sends_a_command_through_process_frame(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    # Guidance is only allowed once the FC reports the AI mode, the mavlink
    # heartbeat looks fresh, and the bridge is actually connected - the
    # minimal test orchestrator has no real MAVLink traffic, so all three
    # must be set by hand (same requirement any FOLLOWING/ORBITING guidance
    # test sending a real setpoint would have).
    orchestrator.mavlink.connect()
    orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
    orchestrator.watchdog.beat("mavlink")
    orchestrator.watchdog.beat("rc_channels")
    person = Detection(bbox=BBox(600, 300, 80, 160), score=0.9, class_id=0, class_name="person", frame_ts=0.0)

    orchestrator._on_target_selected({"x": 640.0, "y": 380.0, "point": True})
    frame = Frame(ts=0.0, width=1280, height=720, raw_detection_output=[person])
    await orchestrator.process_frame(frame)  # initializes tracking on the target
    orchestrator._on_mode_command({"mode": "dronie"})

    frame2 = Frame(ts=0.1, width=1280, height=720, raw_detection_output=[person])
    result = await orchestrator.process_frame(frame2)

    assert result["tracking_state"] == TrackingState.TRACKING
    assert result["supervisor_decision"].state == SupervisorState.SMART_SHOT
    assert result["command_sent"] is True
    recorder.close()


@pytest.mark.asyncio
async def test_smart_shot_finishes_after_its_duration(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator.mavlink.connect()
    orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
    orchestrator.watchdog.beat("mavlink")
    orchestrator.watchdog.beat("rc_channels")
    orchestrator._on_mode_command({"mode": "dronie"})
    duration = orchestrator.smart_shot.limits["duration_s"]

    # dt is the gap between consecutive frame timestamps, so the shot needs
    # a first frame to establish a baseline before a second frame whose gap
    # actually exceeds the shot's duration.
    await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[]))
    await orchestrator.process_frame(
        Frame(ts=duration + 1.0, width=1280, height=720, raw_detection_output=[])
    )

    assert orchestrator.smart_shot.state == SmartShotState.FINISHED
    # A finished shot has no residual safety significance (unlike
    # Approach-Test's boundary stop, which deliberately stays "stuck") -
    # requested_mode drops back to IDLE so supervisor_state (sent to the
    # app every frame) doesn't keep reporting SMART_SHOT forever with no
    # command actually being sent.
    assert orchestrator.requested_mode == SupervisorState.IDLE
    recorder.close()
