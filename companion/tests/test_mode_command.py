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
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
from companion.vision.camera import Frame
from companion.vision.detector import BBox, Detection, PassthroughDetector


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


def test_follow_altitude_override_updates_controller_live(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    assert orchestrator.follow.limits["target_altitude_m"] is None

    orchestrator._on_mode_command({"mode": "follow", "follow_altitude_m": 12.0})

    assert orchestrator.follow.limits["target_altitude_m"] == 12.0
    recorder.close()


def test_on_target_selected_point_payload_stores_point(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)

    orchestrator._on_target_selected({"x": 10.0, "y": 20.0, "point": True})

    assert orchestrator._pending_selection == ("point", 10.0, 20.0)
    recorder.close()


def test_on_target_selected_bbox_payload_stores_bbox(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)

    orchestrator._on_target_selected({"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0})

    kind, bbox = orchestrator._pending_selection
    assert kind == "bbox"
    assert bbox == BBox(1.0, 2.0, 3.0, 4.0)
    recorder.close()


@pytest.mark.asyncio
async def test_point_tap_selects_correct_overlapping_detection(tmp_path):
    """End-to-end through process_frame: tapping a point inside a person
    standing in front of a car selects the person, not the car - the same
    smallest-box-wins behavior verified in isolation in
    test_target_selector.py, now exercised through the real dispatch path."""
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    car = Detection(bbox=BBox(0, 0, 100, 100), score=0.9, class_id=2, class_name="car", frame_ts=0.0)
    person = Detection(bbox=BBox(40, 40, 20, 20), score=0.9, class_id=0, class_name="person", frame_ts=0.0)

    orchestrator._on_target_selected({"x": 50.0, "y": 50.0, "point": True})
    frame = Frame(ts=0.0, width=100, height=100, raw_detection_output=[car, person])
    result = await orchestrator.process_frame(frame)

    assert result["tracking_state"] == TrackingState.TRACKING
    assert orchestrator.state_machine.target.class_name == "person"
    recorder.close()
