import math
import time
from contextlib import contextmanager
from unittest.mock import patch

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

FRAME_W, FRAME_H = 1280, 720
RED = (0, 0, 255)
BLUE = (255, 0, 0)


class _PaintableCamera(CameraBase):
    """Fake camera with real pixels the test can paint, so the appearance
    check sees genuinely different colors under different boxes."""

    def __init__(self) -> None:
        self.width = FRAME_W
        self.height = FRAME_H
        self._frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        self._frame[:, :] = (0, 255, 0)

    def paint(self, bbox: BBox, color) -> None:
        x0, y0 = int(bbox.x), int(bbox.y)
        self._frame[y0:y0 + int(bbox.h), x0:x0 + int(bbox.w)] = color

    def get_latest_frame(self):
        return self._frame


@contextmanager
def _build(tmp_path, camera=None):
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path)
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14770")
        mavlink.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
        orchestrator = CompanionOrchestrator(
            camera=camera,
            detector=PassthroughDetector(),
            tracker=IouKalmanTracker(),
            distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
            follow_controller=FollowController(follow_cfg),
            orbit_controller=OrbitController(orbit_cfg),
            approach_controller=ApproachTestController(approach_cfg),
            mavlink=mavlink,
            rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
            supervisor=SafetySupervisor(watchdog),
            watchdog=watchdog,
            link=link,
            recorder=recorder,
        )
        orchestrator.watchdog.beat("mavlink")
        orchestrator.watchdog.beat("rc_channels")
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
        orchestrator.mavlink.telemetry.armed = True
        orchestrator.mavlink.telemetry.alt_m = 10.0
        orchestrator.mavlink.telemetry.position_ts = time.monotonic()
        yield orchestrator, recorder, conn
        recorder.close()


def _person(bbox: BBox, ts: float = 0.0) -> Detection:
    return Detection(bbox=bbox, score=0.9, class_id=0, class_name="person", frame_ts=ts)


def _frame(ts, detections):
    return Frame(ts=ts, width=FRAME_W, height=FRAME_H, raw_detection_output=detections)


def _velocity_calls(conn):
    """(vx, vy, vz, yaw_rate) of every velocity setpoint sent so far."""
    return [
        (c.args[8], c.args[9], c.args[10], c.args[-1])
        for c in conn.mav.set_position_target_local_ned_send.call_args_list
    ]


# --- app-supplied parameters are clamped to the configured bounds -----------

def test_follow_separation_and_altitude_are_clamped_to_config_bounds(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        limits = orch.follow.limits
        orch._on_mode_command({"mode": "follow", "follow_separation_m": 0.1, "follow_altitude_m": -5.0})
        assert limits["target_separation_m"] == limits["min_separation_m"]
        assert limits["target_altitude_m"] == limits["min_altitude_m"]
        orch._on_mode_command({"mode": "follow", "follow_separation_m": 999.0, "follow_altitude_m": 500.0})
        assert limits["target_separation_m"] == limits["max_separation_m"]
        assert limits["target_altitude_m"] == limits["max_altitude_m"]


def test_orbit_radius_and_altitude_are_clamped_to_config_bounds(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        limits = orch.orbit.limits
        orch._on_mode_command({"mode": "orbit", "orbit_radius_m": 0.5, "orbit_altitude_m": 0.0})
        assert limits["orbit_radius_m"] == limits["min_radius_m"]
        assert limits["target_altitude_m"] == limits["min_altitude_m"]
        orch._on_mode_command({"mode": "orbit", "orbit_radius_m": 500.0, "orbit_altitude_m": 1e6})
        assert limits["orbit_radius_m"] == limits["max_radius_m"]
        assert limits["target_altitude_m"] == limits["max_altitude_m"]


def test_in_range_values_pass_through_unchanged(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        orch._on_mode_command({"mode": "follow", "follow_separation_m": 9.5, "follow_altitude_m": 12.0})
        assert orch.follow.limits["target_separation_m"] == 9.5
        assert orch.follow.limits["target_altitude_m"] == 12.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "abc", [], {}])
def test_non_finite_or_non_numeric_values_are_ignored(tmp_path, bad):
    with _build(tmp_path) as (orch, _rec, _conn):
        before = orch.follow.limits["target_separation_m"]
        orch._on_mode_command({"mode": "follow", "follow_separation_m": bad})
        assert orch.follow.limits["target_separation_m"] == before
        assert math.isfinite(orch.follow.limits["target_separation_m"])


# --- no driving on frozen coordinates ---------------------------------------

async def _follow_a_far_person(orch, conn):
    """Selects an off-center, far person and follows it until 0.2s - leaves a
    nonzero command as the last setpoint."""
    far_person = _person(BBox(300, 300, 80, 160))
    orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
    await orch.process_frame(_frame(0.0, [far_person]))
    orch._on_mode_command({"mode": "follow"})
    await orch.process_frame(_frame(0.1, [far_person]))
    await orch.process_frame(_frame(0.2, [far_person]))
    assert _velocity_calls(conn)[-1] != (0.0, 0.0, 0.0, 0.0)
    return far_person


@pytest.mark.asyncio
async def test_follow_holds_still_once_the_target_has_been_unseen_long_enough(tmp_path):
    """While REACQUIRE, state_machine.target still holds the last box; Follow
    used to keep computing from it (constant yaw rate / forward speed on
    stale coordinates). Past target_hold_after_unseen_s it must command zero."""
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        hold_after = orch.target_hold_after_unseen_s
        result = await orch.process_frame(_frame(0.2 + hold_after, []))
        assert result["tracking_state"] == TrackingState.REACQUIRE
        assert _velocity_calls(conn)[-1] == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.asyncio
async def test_a_single_missed_detection_does_not_make_follow_stutter(tmp_path):
    """The stutter: every missed detection used to drop the command to zero
    for that frame. A miss shorter than target_hold_after_unseen_s keeps
    steering on the last box."""
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        result = await orch.process_frame(_frame(0.25, []))
        assert result["tracking_state"] == TrackingState.REACQUIRE
        assert _velocity_calls(conn)[-1] != (0.0, 0.0, 0.0, 0.0)
        assert _last_tracking_update(orch)["guidance_hold"] is None


@pytest.mark.asyncio
async def test_follow_ramps_up_from_a_standstill_after_a_hold(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        person = _person(BBox(300, 300, 80, 160))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_mode_command({"mode": "follow"})
        for i in range(1, 40):
            await orch.process_frame(_frame(0.1 * i, [person]))
        cruising_vx = _velocity_calls(conn)[-1][0]
        await orch.process_frame(_frame(4.3, []))            # unseen 0.4s -> hold
        assert _velocity_calls(conn)[-1] == (0.0, 0.0, 0.0, 0.0)
        await orch.process_frame(_frame(4.4, [person]))      # target back
        resumed_vx = _velocity_calls(conn)[-1][0]
        assert resumed_vx < cruising_vx
        assert resumed_vx <= orch.follow.limits["max_accel_mps2"] * 0.1 + 1e-9


@pytest.mark.asyncio
async def test_idle_frames_keep_the_follow_controller_at_a_standstill(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        orch.follow._vx_slew.override(2.5)
        orch.follow._distance_pid._integral = 7.0
        await orch.process_frame(_frame(0.0, []))
        assert orch.follow._vx_slew._value == 0.0
        assert orch.follow._distance_pid._integral == 0.0


# --- the tracker cannot silently follow the wrong person --------------------

async def _select_red_target(orch, camera, target_box):
    camera.paint(target_box, RED)
    orch._on_target_selected({"x": target_box.cx, "y": target_box.cy, "point": True})
    await orch.process_frame(_frame(0.0, [_person(target_box)]))
    assert orch.appearance.has_signature


@pytest.mark.asyncio
async def test_swap_to_a_lookalike_bystander_is_detected_and_corrected(tmp_path):
    camera = _PaintableCamera()
    with _build(tmp_path, camera) as (orch, rec, _conn):
        original_box = BBox(200, 200, 80, 160)
        await _select_red_target(orch, camera, original_box)

        # Two people cross: a blue stranger walks into the spot the tracker
        # is following, while the red target is now standing elsewhere.
        stranger_box = original_box
        real_target_box = BBox(700, 200, 80, 160)
        camera.paint(stranger_box, BLUE)
        camera.paint(real_target_box, RED)
        detections = [_person(stranger_box), _person(real_target_box)]

        for i in range(1, 12):
            await orch.process_frame(_frame(0.05 * i, detections))

        assert orch.state_machine.target.bbox.x == real_target_box.x
        assert orch.state_machine.state == TrackingState.TRACKING


@pytest.mark.asyncio
async def test_sustained_mismatch_with_no_alternative_stops_following(tmp_path):
    camera = _PaintableCamera()
    with _build(tmp_path, camera) as (orch, rec, conn):
        original_box = BBox(200, 200, 80, 160)
        await _select_red_target(orch, camera, original_box)
        orch._on_mode_command({"mode": "follow"})

        camera.paint(original_box, BLUE)  # a stranger is now where the target was; the target is gone
        states = []
        for i in range(1, 40):
            result = await orch.process_frame(_frame(0.05 * i, [_person(original_box)]))
            states.append(result["tracking_state"])

        assert TrackingState.REACQUIRE in states
        assert states[-1] != TrackingState.TRACKING
        # ...and once dropped, the aircraft is holding, not pursuing the stranger.
        assert _velocity_calls(conn)[-1] == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.asyncio
async def test_the_same_person_never_triggers_the_identity_check(tmp_path):
    camera = _PaintableCamera()
    with _build(tmp_path, camera) as (orch, rec, _conn):
        box = BBox(200, 200, 80, 160)
        await _select_red_target(orch, camera, box)
        for i in range(1, 60):
            result = await orch.process_frame(_frame(0.05 * i, [_person(box)]))
            assert result["tracking_state"] == TrackingState.TRACKING
        assert orch._identity_mismatch_frames == 0


@pytest.mark.asyncio
async def test_a_brief_mismatch_does_not_drop_a_target_that_recovers(tmp_path):
    """A person turning around or passing through shade for a few frames
    must not lose the lock."""
    camera = _PaintableCamera()
    with _build(tmp_path, camera) as (orch, rec, _conn):
        box = BBox(200, 200, 80, 160)
        await _select_red_target(orch, camera, box)
        camera.paint(box, BLUE)
        for i in range(1, 4):
            await orch.process_frame(_frame(0.05 * i, [_person(box)]))
        camera.paint(box, RED)
        for i in range(4, 30):
            result = await orch.process_frame(_frame(0.05 * i, [_person(box)]))
        assert result["tracking_state"] == TrackingState.TRACKING
        assert orch._identity_mismatch_frames == 0


@pytest.mark.asyncio
async def test_identity_check_is_a_no_op_without_real_frames(tmp_path):
    """Sim mode has no pixel data - the check must simply not run."""
    with _build(tmp_path, camera=None) as (orch, rec, _conn):
        box = BBox(200, 200, 80, 160)
        orch._on_target_selected({"x": 240.0, "y": 280.0, "point": True})
        for i in range(30):
            result = await orch.process_frame(_frame(0.05 * i, [_person(box)]))
        assert result["tracking_state"] == TrackingState.TRACKING


# --- the operator is told *why* the drone is holding -----------------------

def _last_tracking_update(orch):
    import json

    for raw in reversed(orch.link.transport.sent):
        msg = json.loads(raw)
        if msg["type"] == "tracking_update":
            return msg["payload"]
    raise AssertionError("no tracking_update was sent")


@pytest.mark.asyncio
async def test_hold_reason_is_reported_while_the_target_is_unseen(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        person = _person(BBox(300, 300, 80, 160))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_mode_command({"mode": "follow"})
        await orch.process_frame(_frame(0.1, [person]))
        assert _last_tracking_update(orch)["guidance_hold"] is None  # normal following: nothing held

        await orch.process_frame(_frame(0.4, []))  # unseen 0.3s
        update = _last_tracking_update(orch)
        assert update["guidance_hold"] == "target_unseen"
        assert update["guidance_sent"] is True  # a zero-velocity hold was actually sent


@pytest.mark.asyncio
async def test_hold_reason_distinguishes_a_failed_identity_check(tmp_path):
    camera = _PaintableCamera()
    with _build(tmp_path, camera) as (orch, _rec, _conn):
        box = BBox(200, 200, 80, 160)
        await _select_red_target(orch, camera, box)
        orch._on_mode_command({"mode": "follow"})
        camera.paint(box, BLUE)
        for i in range(1, 40):
            await orch.process_frame(_frame(0.05 * i, [_person(box)]))
        assert _last_tracking_update(orch)["guidance_hold"] == "identity_lost"


@pytest.mark.asyncio
async def test_hold_reason_clears_once_the_target_is_tracked_again(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        person = _person(BBox(300, 300, 80, 160))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_mode_command({"mode": "follow"})
        await orch.process_frame(_frame(0.4, []))  # unseen 0.4s
        assert _last_tracking_update(orch)["guidance_hold"] == "target_unseen"
        await orch.process_frame(_frame(0.5, [person]))
        assert _last_tracking_update(orch)["guidance_hold"] is None


@pytest.mark.asyncio
async def test_hold_reason_reports_the_takeoff_climb(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        orch.mavlink.telemetry.alt_m = 0.0
        orch.mavlink.telemetry.position_ts = time.monotonic()
        person = _person(BBox(300, 300, 80, 160))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_mode_command({"mode": "follow", "auto_takeoff": True})
        await orch.process_frame(_frame(0.1, [person]))
        update = _last_tracking_update(orch)
        assert update["guidance_hold"] == "auto_takeoff"
        assert update["guidance_sent"] is False


# --- frames with no AI result (the detection flicker) -------------------------

def _last_detections_update(orch):
    import json

    for raw in reversed(orch.link.transport.sent):
        msg = json.loads(raw)
        if msg["type"] == "detections_update":
            return msg["payload"]
    raise AssertionError("no detections_update was sent")


def _no_result_frame(ts):
    """A camera frame the AI attached no result to (IMX500 outputs=None)."""
    return Frame(ts=ts, width=FRAME_W, height=FRAME_H, raw_detection_output=None)


@pytest.mark.asyncio
async def test_a_frame_with_no_ai_result_keeps_tracking(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        result = await orch.process_frame(_no_result_frame(0.233))
        assert result["tracking_state"] == TrackingState.TRACKING
        assert _velocity_calls(conn)[-1] != (0.0, 0.0, 0.0, 0.0)


@pytest.mark.asyncio
async def test_frames_with_no_ai_result_do_not_update_the_tracker(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        with patch.object(orch.state_machine.tracker, "update", wraps=orch.state_machine.tracker.update) as update:
            await orch.process_frame(_no_result_frame(0.233))
            await orch.process_frame(_no_result_frame(0.266))
            update.assert_not_called()
        assert orch.state_machine.target.last_seen_ts == 0.2


@pytest.mark.asyncio
async def test_the_app_keeps_seeing_the_last_boxes_on_a_frame_with_no_ai_result(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        await orch.process_frame(_no_result_frame(0.233))
        boxes = _last_detections_update(orch)["detections"]
        assert [b["bbox"] for b in boxes] == [{"x": 300, "y": 300, "w": 80, "h": 160}]


@pytest.mark.asyncio
async def test_a_tap_on_a_carried_over_box_still_selects_it(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        person = _person(BBox(300, 300, 80, 160))
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        result = await orch.process_frame(_no_result_frame(0.033))
        assert result["tracking_state"] == TrackingState.TRACKING


@pytest.mark.asyncio
async def test_follow_holds_when_ai_results_stop_even_though_still_tracking(tmp_path):
    """The hold is about the target's age, not the tracking state: a TRACKING
    target whose results stopped arriving must not be steered on forever."""
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        result = await orch.process_frame(_no_result_frame(0.2 + orch.target_hold_after_unseen_s))
        assert result["tracking_state"] == TrackingState.TRACKING
        assert _velocity_calls(conn)[-1] == (0.0, 0.0, 0.0, 0.0)
        assert _last_tracking_update(orch)["guidance_hold"] == "target_unseen"


@pytest.mark.asyncio
async def test_carried_detections_expire_and_then_count_as_seeing_nothing(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        expired = 0.2 + orch.detection_carry_max_s + 0.05
        result = await orch.process_frame(_no_result_frame(expired))
        assert result["tracking_state"] == TrackingState.REACQUIRE
        assert _last_detections_update(orch)["detections"] == []


@pytest.mark.asyncio
async def test_a_stopped_ai_eventually_loses_the_target(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        await _follow_a_far_person(orch, conn)
        ts, state = 0.2, None
        while ts < 0.2 + orch.detection_carry_max_s + orch.state_machine.reacquire_timeout_s + 0.2:
            ts += 0.1
            state = (await orch.process_frame(_no_result_frame(ts)))["tracking_state"]
        assert state == TrackingState.TARGET_LOST


@pytest.mark.asyncio
async def test_the_identity_check_is_skipped_on_frames_with_no_ai_result(tmp_path):
    """The carried box is from an older image; comparing it to the current
    pixels would count honest motion as an identity mismatch."""
    camera = _PaintableCamera()
    with _build(tmp_path, camera) as (orch, _rec, _conn):
        box = BBox(200, 200, 80, 160)
        await _select_red_target(orch, camera, box)
        with patch.object(orch, "_verify_tracked_identity", wraps=orch._verify_tracked_identity) as verify:
            await orch.process_frame(_no_result_frame(0.033))
            verify.assert_not_called()
            await orch.process_frame(_frame(0.066, [_person(box)]))
            verify.assert_called_once()
