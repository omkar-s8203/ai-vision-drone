import numpy as np
import pytest

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
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
from companion.vision.camera import CameraBase, Frame
from companion.vision.detector import BBox, Detection, PassthroughDetector

FRAME_W, FRAME_H = 200, 200
REACQUIRE_TIMEOUT_S = 0.5


class _SolidColorCamera(CameraBase):
    """A fake camera whose get_latest_frame() always returns the same
    solid-color image - real pixel data (needed for appearance learning/
    matching) without needing picamera2. Both the original selection and
    the later reappearance sample the same color, which is enough to prove
    the wiring calls learn()/find_match() correctly; the histogram
    similarity math itself is covered in isolation by test_appearance.py."""

    def __init__(self) -> None:
        self.width = FRAME_W
        self.height = FRAME_H
        self._frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        self._frame[:, :] = (0, 0, 255)

    def get_latest_frame(self):
        return self._frame


def _build_orchestrator(tmp_path, reacquire_timeout_s=REACQUIRE_TIMEOUT_S):
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path)
    orchestrator = CompanionOrchestrator(
        camera=_SolidColorCamera(),
        detector=PassthroughDetector(),
        tracker=IouKalmanTracker(),
        distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
        follow_controller=FollowController(follow_cfg),
        orbit_controller=OrbitController(orbit_cfg),
        approach_controller=ApproachTestController(approach_cfg),
        mavlink=MavlinkBridge("udpin:127.0.0.1:14710"),
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
        reacquire_timeout_s=reacquire_timeout_s,
    )
    return orchestrator, recorder


def _person(bbox: BBox, ts: float) -> Detection:
    return Detection(bbox=bbox, score=0.9, class_id=0, class_name="person", frame_ts=ts)


@pytest.mark.asyncio
async def test_target_lost_then_reappearing_is_auto_reacquired(tmp_path):
    orchestrator, recorder = _build_orchestrator(tmp_path)
    original_bbox = BBox(x=50, y=50, w=40, h=80)

    # Select the target - triggers state_machine.start() + appearance.learn().
    orchestrator._on_target_selected({"x": 70.0, "y": 90.0, "point": True})
    await orchestrator.process_frame(
        Frame(ts=0.0, width=FRAME_W, height=FRAME_H, raw_detection_output=[_person(original_bbox, 0.0)])
    )
    assert orchestrator.state_machine.state == TrackingState.TRACKING
    assert orchestrator.appearance.has_signature is True

    # Target vanishes from every subsequent frame's detections long enough
    # to cross REACQUIRE -> TARGET_LOST.
    result = await orchestrator.process_frame(Frame(ts=0.1, width=FRAME_W, height=FRAME_H, raw_detection_output=[]))
    assert result["tracking_state"] == TrackingState.REACQUIRE

    result = await orchestrator.process_frame(
        Frame(ts=0.1 + REACQUIRE_TIMEOUT_S + 0.1, width=FRAME_W, height=FRAME_H, raw_detection_output=[])
    )
    assert result["tracking_state"] == TrackingState.TARGET_LOST
    assert orchestrator.state_machine.target is None

    # The same subject reappears elsewhere in frame - same class, same
    # remembered color (the fake camera is solid-color everywhere) - should
    # auto-relock without any new _on_target_selected call.
    reappeared_bbox = BBox(x=120, y=100, w=40, h=80)
    result = await orchestrator.process_frame(
        Frame(
            ts=5.0, width=FRAME_W, height=FRAME_H,
            raw_detection_output=[_person(reappeared_bbox, 5.0)],
        )
    )

    assert result["tracking_state"] == TrackingState.TRACKING
    assert orchestrator.state_machine.target is not None
    assert orchestrator.state_machine.target.bbox == reappeared_bbox
    recorder.close()


@pytest.mark.asyncio
async def test_abort_forgets_the_target_so_it_does_not_silently_relock(tmp_path):
    orchestrator, recorder = _build_orchestrator(tmp_path)
    orchestrator._on_target_selected({"x": 70.0, "y": 90.0, "point": True})
    await orchestrator.process_frame(
        Frame(ts=0.0, width=FRAME_W, height=FRAME_H, raw_detection_output=[_person(BBox(50, 50, 40, 80), 0.0)])
    )
    assert orchestrator.appearance.has_signature is True

    orchestrator._on_abort({"reason": "operator"})

    assert orchestrator.appearance.has_signature is False
    recorder.close()


@pytest.mark.asyncio
async def test_reselecting_a_different_target_while_already_tracking_switches_immediately(tmp_path):
    """A real field-reported bug ("I can't select a detection object"): the
    pending-selection handler used to only fire while
    state_machine.state == IDLE, which it never returns to on its own once
    ANY target has ever been selected (TRACKING -> REACQUIRE -> TARGET_LOST,
    then stuck there short of an explicit Abort) - so every TARGET_SELECT
    after the very first one was silently swallowed. An explicit operator
    re-selection (tap-on-video or "Select" in the AI Modes detection list)
    must always take effect immediately, switching the tracked target
    without needing to Abort first."""
    orchestrator, recorder = _build_orchestrator(tmp_path)
    person_a_bbox = BBox(x=20, y=20, w=30, h=60)
    person_b_bbox = BBox(x=140, y=20, w=30, h=60)

    orchestrator._on_target_selected({"x": 35.0, "y": 50.0, "point": True})
    await orchestrator.process_frame(
        Frame(
            ts=0.0, width=FRAME_W, height=FRAME_H,
            raw_detection_output=[_person(person_a_bbox, 0.0), _person(person_b_bbox, 0.0)],
        )
    )
    assert orchestrator.state_machine.state == TrackingState.TRACKING
    first_target_id = orchestrator.state_machine.target.target_id

    # Still TRACKING person A (never lost) - re-selecting person B must
    # still switch immediately, not be ignored because state isn't IDLE.
    orchestrator._on_target_selected({"x": 155.0, "y": 50.0, "point": True})
    result = await orchestrator.process_frame(
        Frame(
            ts=0.1, width=FRAME_W, height=FRAME_H,
            raw_detection_output=[_person(person_a_bbox, 0.1), _person(person_b_bbox, 0.1)],
        )
    )

    assert result["tracking_state"] == TrackingState.TRACKING
    assert orchestrator.state_machine.target.bbox == person_b_bbox
    assert orchestrator.state_machine.target.target_id != first_target_id
    recorder.close()


@pytest.mark.asyncio
async def test_no_reacquire_without_a_learned_signature(tmp_path):
    """Sanity check: if nothing was ever selected, a stray same-class
    detection must never spontaneously start tracking on its own."""
    orchestrator, recorder = _build_orchestrator(tmp_path)

    result = await orchestrator.process_frame(
        Frame(ts=0.0, width=FRAME_W, height=FRAME_H, raw_detection_output=[_person(BBox(50, 50, 40, 80), 0.0)])
    )

    assert result["tracking_state"] == TrackingState.IDLE
    recorder.close()
