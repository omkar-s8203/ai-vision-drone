from contextlib import contextmanager
from unittest.mock import patch

import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.grid_search import GridSearchController, GridSearchPhase
from companion.guidance.orbit import OrbitController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor, SupervisorState
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.camera import Frame
from companion.vision.detector import PassthroughDetector

# Fast, deterministic limits distinct from the real grid_search_limits.yaml
# defaults, so these tests reach a waypoint / finish quickly and
# deterministically.
FAST_GRID_SEARCH_LIMITS = {
    "leg_spacing_m": 10.0,
    "search_speed_mps": 2.5,
    "waypoint_radius_m": 3.0,
    "max_heading_error_deg_to_advance": 25.0,
    "max_yaw_rate_rads": 0.5,
    "max_speed_mps": 2.5,
    "search_altitude_m": None,
    "pid": {"yaw": {"kp": 0.02, "ki": 0.0, "kd": 0.005}, "altitude": {"kp": 0.5, "ki": 0.05, "kd": 0.1}},
}


@contextmanager
def _build_orchestrator(tmp_path):
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    transport = FakeTransport(connected=True)
    link = GroundStationLink(transport)
    recorder = SessionRecorder(tmp_path / "session")
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14790")
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
            grid_search_controller=GridSearchController(dict(FAST_GRID_SEARCH_LIMITS)),
        )
        yield orchestrator, recorder, conn, transport


def _ready_for_guidance(orchestrator):
    """The minimum needed for guidance_allowed: FC in GUIDED, required
    subsystems fresh, no RC override."""
    orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
    orchestrator.watchdog.beat("camera")
    orchestrator.watchdog.beat("tracker")
    orchestrator.watchdog.beat("mavlink")
    orchestrator.watchdog.beat("comms")
    orchestrator.watchdog.beat("rc_channels")


def test_grid_search_mode_command_starts_the_sweep_from_current_position(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194

        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 20.0}
        )

        assert orchestrator.grid_search.is_active is True
        assert orchestrator.requested_mode == SupervisorState.GRID_SEARCH
        assert len(orchestrator.grid_search.status().waypoints) >= 2
        recorder.close()


def test_grid_search_mode_command_without_gps_fix_falls_back_to_idle(tmp_path):
    """A real fail-safe check: missing GPS telemetry must not silently
    report GRID_SEARCH as active with nothing planned - see
    _on_mode_command's own reasoning (mirrors TargetRecoveryController's
    "missing telemetry defaults to the safe choice" pattern)."""
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        assert orchestrator.mavlink.telemetry.lat is None

        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 20.0}
        )

        assert orchestrator.grid_search.is_active is False
        assert orchestrator.requested_mode == SupervisorState.IDLE
        recorder.close()


def test_grid_search_mode_command_without_dimensions_falls_back_to_idle(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194

        orchestrator._on_mode_command({"mode": "grid_search"})

        assert orchestrator.grid_search.is_active is False
        assert orchestrator.requested_mode == SupervisorState.IDLE
        recorder.close()


@pytest.mark.asyncio
async def test_grid_search_sends_a_real_velocity_setpoint_through_process_frame(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194
        orchestrator.mavlink.telemetry.heading_deg = 0.0
        orchestrator.mavlink.telemetry.alt_m = 15.0
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 20.0}
        )
        _ready_for_guidance(orchestrator)

        result = await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[]))

        assert result["supervisor_decision"].state == SupervisorState.GRID_SEARCH
        assert result["supervisor_decision"].guidance_allowed is True
        conn.mav.set_position_target_local_ned_send.assert_called_once()
        recorder.close()


def test_abort_resets_an_active_grid_search(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 20.0}
        )
        assert orchestrator.grid_search.is_active is True

        orchestrator._on_abort({"reason": "operator"})

        assert orchestrator.grid_search.is_active is False
        assert orchestrator.grid_search.phase == GridSearchPhase.IDLE
        recorder.close()


def test_switching_away_from_grid_search_resets_it(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 20.0}
        )
        assert orchestrator.grid_search.is_active is True

        orchestrator._on_mode_command({"mode": "idle"})

        assert orchestrator.grid_search.is_active is False
        recorder.close()


@pytest.mark.asyncio
async def test_grid_search_finishing_drops_back_to_idle(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 0.0
        orchestrator.mavlink.telemetry.lon = 0.0
        orchestrator.mavlink.telemetry.heading_deg = 0.0
        # A tiny area with a coarse spacing plans the fewest possible
        # waypoints (one leg) so the sweep can be driven to completion in
        # a handful of frames instead of a long, slow simulated flight.
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 10.0, "grid_search_height_m": 1.0}
        )
        _ready_for_guidance(orchestrator)
        waypoints = orchestrator.grid_search.status().waypoints

        for lat, lon in waypoints:
            orchestrator.mavlink.telemetry.lat = lat
            orchestrator.mavlink.telemetry.lon = lon
            _ready_for_guidance(orchestrator)  # re-beat watchdogs each frame
            await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[]))

        assert orchestrator.grid_search.phase == GridSearchPhase.FINISHED
        assert orchestrator.grid_search.is_active is False
        assert orchestrator.requested_mode == SupervisorState.IDLE
        recorder.close()


@pytest.mark.asyncio
async def test_a_finished_grid_search_is_reset_on_the_next_mode_switch(tmp_path):
    """A deep-audit gap: _on_mode_command()'s reset branch used to check
    `self.grid_search.is_active` (True only while SEARCHING), so once a
    sweep finished on its own (phase -> FINISHED, is_active -> False), the
    very next mode switch away never reset it at all - the stale finished
    route (waypoints/current_index) kept streaming to the app's flight map
    indefinitely, across unrelated later modes, until an explicit abort()
    happened to be called instead."""
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 0.0
        orchestrator.mavlink.telemetry.lon = 0.0
        orchestrator.mavlink.telemetry.heading_deg = 0.0
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 10.0, "grid_search_height_m": 1.0}
        )
        _ready_for_guidance(orchestrator)
        waypoints = orchestrator.grid_search.status().waypoints
        for lat, lon in waypoints:
            orchestrator.mavlink.telemetry.lat = lat
            orchestrator.mavlink.telemetry.lon = lon
            _ready_for_guidance(orchestrator)
            await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[]))
        assert orchestrator.grid_search.phase == GridSearchPhase.FINISHED

        orchestrator._on_mode_command({"mode": "follow"})

        assert orchestrator.grid_search.phase == GridSearchPhase.IDLE
        assert orchestrator.grid_search.status().waypoints == []
        recorder.close()


@pytest.mark.asyncio
async def test_a_finished_grid_search_is_reset_even_if_the_next_start_attempt_fails(tmp_path):
    """A code-review audit caught a real gap in the fix above: it only
    covered switching to a *different* mode after a sweep finished. Trying
    to start a *new* grid search that then fails validation (missing GPS,
    or missing width_m/height_m - e.g. a momentary GPS dropout) falls into
    a separate branch that never called reset() either, leaving the
    previous sweep's stale FINISHED state (with its old waypoints) still
    streaming to the app indefinitely."""
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        orchestrator.mavlink.telemetry.lat = 0.0
        orchestrator.mavlink.telemetry.lon = 0.0
        orchestrator.mavlink.telemetry.heading_deg = 0.0
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 10.0, "grid_search_height_m": 1.0}
        )
        _ready_for_guidance(orchestrator)
        waypoints = orchestrator.grid_search.status().waypoints
        for lat, lon in waypoints:
            orchestrator.mavlink.telemetry.lat = lat
            orchestrator.mavlink.telemetry.lon = lon
            _ready_for_guidance(orchestrator)
            await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[]))
        assert orchestrator.grid_search.phase == GridSearchPhase.FINISHED

        # Simulate a momentary GPS dropout on the next start attempt.
        orchestrator.mavlink.telemetry.lat = None
        orchestrator.mavlink.telemetry.lon = None
        orchestrator._on_mode_command(
            {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 20.0}
        )

        assert orchestrator.grid_search.phase == GridSearchPhase.IDLE
        assert orchestrator.grid_search.status().waypoints == []
        assert orchestrator.requested_mode == SupervisorState.IDLE
        recorder.close()
