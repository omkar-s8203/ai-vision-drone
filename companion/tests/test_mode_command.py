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
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.detector import PassthroughDetector


def _build_minimal_orchestrator(tmp_path):
    follow_cfg = load_yaml("follow_limits.yaml")
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
        approach_controller=ApproachTestController(approach_cfg),
        mavlink=MavlinkBridge("udpin:127.0.0.1:14680"),
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
    )
    return orchestrator, recorder


def test_follow_separation_override_updates_controller_live(tmp_path):
    """The Android follow-separation slider sends follow_separation_m on the
    mode_command message; the Pi must apply it to the live FollowController,
    not just remember it for next startup (docs android/README known gap)."""
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    default_separation = orchestrator.follow.limits["target_separation_m"]

    orchestrator._on_mode_command({"mode": "follow", "follow_separation_m": 9.5})

    assert orchestrator.follow.limits["target_separation_m"] == 9.5
    assert 9.5 != default_separation
    recorder.close()


def test_mode_command_without_separation_leaves_default(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    default_separation = orchestrator.follow.limits["target_separation_m"]

    orchestrator._on_mode_command({"mode": "follow"})

    assert orchestrator.follow.limits["target_separation_m"] == default_separation
    recorder.close()
