from contextlib import contextmanager
from unittest.mock import patch

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


def test_freshly_entering_follow_resets_pid_state(tmp_path):
    """A real bug found in a code-review audit: FollowController.reset()
    existed but was never called from main.py. Windup accumulated during a
    previous Follow stint (or while a large tracking error built up before
    the operator switched away) would otherwise bleed into the next
    session as a velocity-command transient sized by stale error, not the
    current one."""
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator._on_mode_command({"mode": "follow"})
    orchestrator.follow._distance_pid._integral = 42.0  # simulate accumulated windup

    orchestrator._on_mode_command({"mode": "idle"})
    orchestrator._on_mode_command({"mode": "follow"})

    assert orchestrator.follow._distance_pid._integral == 0.0
    recorder.close()


def test_live_parameter_update_while_already_in_follow_does_not_reset_pid(tmp_path):
    """The reset above must only fire on a fresh (re)entry into Follow, not
    on every mode_command while already active - the Android separation/
    altitude sliders resend {"mode": "follow", ...} on every drag, and
    resetting the PID mid-adjustment would fight the operator's own tuning."""
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator._on_mode_command({"mode": "follow"})
    orchestrator.follow._distance_pid._integral = 42.0

    orchestrator._on_mode_command({"mode": "follow", "follow_separation_m": 9.5})

    assert orchestrator.follow._distance_pid._integral == 42.0
    recorder.close()


def test_follow_max_speed_override_updates_controller_live(tmp_path):
    """The Android speed slider sends follow_max_speed_mps on the
    mode_command message; the Pi must apply it live via
    FollowController.set_max_speed(), same as the separation/altitude
    sliders already do for their own fields."""
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    ceiling = orchestrator.follow.limits["max_speed_mps"]

    orchestrator._on_mode_command({"mode": "follow", "follow_max_speed_mps": 1.0})
    assert orchestrator.follow.limits["max_speed_mps"] == 1.0

    # Clamped to the config ceiling, not applied verbatim, if the app ever
    # sent something above it.
    orchestrator._on_mode_command({"mode": "follow", "follow_max_speed_mps": ceiling + 100.0})
    assert orchestrator.follow.limits["max_speed_mps"] == ceiling
    recorder.close()


def test_orbit_max_speed_override_updates_controller_live(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)

    orchestrator._on_mode_command({"mode": "orbit", "orbit_max_speed_mps": 1.5})

    assert orchestrator.orbit.limits["max_speed_mps"] == 1.5
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


@contextmanager
def _build_connected_orchestrator(tmp_path):
    """Unlike _build_minimal_orchestrator above, this one actually connects
    MavlinkBridge (with mavutil mocked) - needed to exercise the auto-GUIDED
    request, which calls MavlinkBridge.set_mode() and would hit its own
    "call connect() first" assert otherwise."""
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path)
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14691")
        mavlink.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
        orchestrator = CompanionOrchestrator(
            camera=None,
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
        yield orchestrator, recorder, conn


def test_selecting_follow_automatically_requests_guided(tmp_path):
    """A field-reported UX gap found during real FLTMODE_CH testing:
    selecting a target and choosing a guidance mode used to do nothing
    observable until the pilot separately switched the FC to GUIDED -
    selecting Follow should be enough on its own now."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "STABILIZE"

        orchestrator._on_mode_command({"mode": "follow"})

        conn.mav.set_mode_send.assert_called_once_with(1, 1, 4)  # GUIDED = 4
        recorder.close()


@pytest.mark.parametrize(
    "mode_str,payload_extra",
    [
        ("follow", {}),
        ("orbit", {}),
        ("approach", {}),
        ("grid_search", {"grid_search_width_m": 60.0, "grid_search_height_m": 20.0}),
    ],
)
def test_every_mode_requiring_guided_requests_it(tmp_path, mode_str, payload_extra):
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "STABILIZE"
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194
        orchestrator.mavlink.telemetry.gps_fix_type = 3  # grid search refuses to start without a real fix

        orchestrator._on_mode_command({"mode": mode_str, **payload_extra})

        conn.mav.set_mode_send.assert_called_once_with(1, 1, 4)
        recorder.close()


def test_selecting_idle_or_tracking_never_requests_guided(tmp_path):
    """TRACKING is vision-only (no velocity command, never Supervisor-gated)
    - it must never trigger a real FC mode change."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "STABILIZE"

        orchestrator._on_mode_command({"mode": "tracking"})
        orchestrator._on_mode_command({"mode": "idle"})

        conn.mav.set_mode_send.assert_not_called()
        recorder.close()


def test_auto_guided_is_never_requested_while_rc_override_is_active(tmp_path):
    """The pilot already has manual control - a mode change from the Pi
    would fight it, the same reasoning already applied to target-recovery's
    RTL suppression."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "STABILIZE"
        orchestrator.mavlink.telemetry.rc_channels = {1: 2000, 2: 1500, 3: 1500, 4: 1500}  # roll deflected

        orchestrator._on_mode_command({"mode": "follow"})

        conn.mav.set_mode_send.assert_not_called()
        recorder.close()


def test_auto_guided_is_a_no_op_when_already_in_guided(tmp_path):
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"

        orchestrator._on_mode_command({"mode": "follow"})

        conn.mav.set_mode_send.assert_not_called()
        recorder.close()
