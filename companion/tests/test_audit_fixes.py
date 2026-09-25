"""Regression tests for the 2026-09 safety audit: MAVLink heartbeat source
filtering, the companion's own component ID, stop-on-withdrawn-guidance, the
on-ground guard, the throttle-stick false override, PID anti-windup, and the
target-recovery RTL / land-confirmation gating."""

import math
from unittest.mock import MagicMock, patch

import pytest

from companion.guidance.auto_takeoff import AutoTakeoffController
from companion.guidance.pid import Pid
from companion.mavlink.bridge import MAV_LANDED_STATE_ON_GROUND, MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SupervisorState
from companion.tests.test_failsafes_and_freshness import GRID, _grid_ready, _last_update
from companion.tests.test_tracking_safety_orchestrator import _build, _frame, _person, _velocity_calls
from companion.vision.camera import Frame
from companion.vision.detector import BBox


# --- MAVLink bridge ---------------------------------------------------------

def _bridge():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14790")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED = 128
        return bridge, conn


def _heartbeat(src_system, src_component, autopilot, mode_name, base_mode=0):
    msg = MagicMock()
    msg.get_type.return_value = "HEARTBEAT"
    msg.get_srcSystem.return_value = src_system
    msg.get_srcComponent.return_value = src_component
    msg.autopilot = autopilot
    msg.base_mode = base_mode
    msg.mode_name = mode_name
    return msg


def test_a_gcs_heartbeat_routed_by_the_fc_does_not_overwrite_fc_state():
    """ArduPilot forwards the GCS's heartbeat (sysid 255, MAV_AUTOPILOT_INVALID)
    to the companion port. It used to become fc_mode/armed and the command target."""
    bridge, conn = _bridge()
    bridge._handle_message(_heartbeat(1, 1, autopilot=3, mode_name="GUIDED", base_mode=128))
    fc_mode = bridge.telemetry.fc_mode
    bridge._handle_message(_heartbeat(255, 190, autopilot=8, mode_name="Mode(0x00)", base_mode=0))

    assert bridge.telemetry.fc_mode == fc_mode
    assert bridge.telemetry.armed is True
    assert (conn.target_system, conn.target_component) == (1, 1)


def test_a_non_autopilot_component_on_the_vehicle_is_ignored_too():
    bridge, conn = _bridge()
    bridge._handle_message(_heartbeat(1, 1, autopilot=3, mode_name="LOITER", base_mode=128))
    bridge._handle_message(_heartbeat(1, 154, autopilot=8, mode_name="Mode(0x00)"))  # a gimbal
    assert bridge.telemetry.armed is True
    assert conn.target_component == 1


def test_the_bridge_identifies_itself_as_an_onboard_computer():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        MavlinkBridge("udpin:127.0.0.1:14791").connect()
        assert mock_mavutil.mavlink_connection.call_args.kwargs["source_component"] == 191


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_setpoint_is_never_sent(bad):
    bridge, conn = _bridge()
    assert bridge.send_velocity_setpoint(bad, 0.0, 0.0, 0.0, guidance_allowed=True) is False
    assert bridge.send_velocity_setpoint(0.0, 0.0, 0.0, bad, guidance_allowed=True) is False
    conn.mav.set_position_target_local_ned_send.assert_not_called()


def test_landed_state_is_read_from_extended_sys_state():
    bridge, _conn = _bridge()
    assert bridge.on_ground is False  # unknown is not "on the ground"
    msg = MagicMock()
    msg.get_type.return_value = "EXTENDED_SYS_STATE"
    msg.landed_state = MAV_LANDED_STATE_ON_GROUND
    bridge._handle_message(msg)
    assert bridge.on_ground is True
    msg.landed_state = 2  # IN_AIR
    bridge._handle_message(msg)
    assert bridge.on_ground is False


# --- RC override monitor ----------------------------------------------------

def test_throttle_at_the_bottom_is_not_read_as_override():
    """The throttle stick does not self-centre and sits low after arming."""
    monitor = RcOverrideMonitor(deadband=0.15)
    assert monitor.is_overriding({1: 1500, 2: 1500, 3: 1000, 4: 1500}) is False
    assert monitor.is_overriding({1: 1500, 2: 1500, 3: 1500, 4: 1900}) is True  # yaw still counts


# --- PID / auto-takeoff -----------------------------------------------------

def test_pid_integral_cannot_wind_up_past_the_output_limit():
    pid = Pid(kp=0.0, ki=1.0, kd=0.0, out_limit=2.0)
    for _ in range(1000):
        pid.step(10.0, 0.1)  # long saturated stretch
    # One step of the opposite sign must already pull the output off the rail.
    assert pid.step(-10.0, 0.1) < 2.0


def test_auto_takeoff_already_at_altitude_is_ready_without_a_takeoff():
    ctl = AutoTakeoffController({"altitude_m": 10.0, "altitude_tolerance_m": 1.0, "timeout_s": 30.0})
    ctl.start()
    assert ctl.update(armed=True, fc_mode="GUIDED", current_alt_m=12.0, dt=0.1) == "ready"


# --- orchestrator -----------------------------------------------------------

async def _following(orch):
    person = _person(BBox(300, 300, 80, 160))
    orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
    await orch.process_frame(_frame(0.0, [person]))
    orch._on_mode_command({"mode": "follow"})
    await orch.process_frame(_frame(0.1, [person]))
    return person


@pytest.mark.asyncio
async def test_withdrawn_guidance_is_followed_by_an_explicit_stop(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        person = await _following(orch)
        assert any(v != (0.0, 0.0, 0.0, 0.0) for v in _velocity_calls(conn))
        before = len(_velocity_calls(conn))

        orch.mavlink.telemetry.battery_remaining_pct = 5  # -> SAFE: battery_critical
        for i in range(6):
            orch.mavlink.telemetry.fc_mode = "GUIDED"  # keep it GUIDED despite the RTL request
            await orch.process_frame(_frame(0.2 + 0.05 * i, [person]))

        stops = _velocity_calls(conn)[before:]
        assert stops == [(0.0, 0.0, 0.0, 0.0)] * 3  # repeated, then silence


@pytest.mark.asyncio
async def test_no_stop_is_sent_once_the_fc_has_left_guided(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        person = await _following(orch)
        before = len(_velocity_calls(conn))
        orch.mavlink.telemetry.fc_mode = "LOITER"  # pilot's mode switch
        await orch.process_frame(_frame(0.2, [person]))
        assert len(_velocity_calls(conn)) == before


@pytest.mark.asyncio
async def test_no_guidance_is_sent_while_the_fc_reports_on_ground(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.landed_state = MAV_LANDED_STATE_ON_GROUND
        await _following(orch)
        assert _velocity_calls(conn) == []
        assert _last_update(orch)["guidance_hold"] == "on_ground"


@pytest.mark.asyncio
async def test_grid_search_nan_heading_falls_back_to_the_compass(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        _grid_ready(orch)
        orch._on_mode_command({**GRID, "grid_search_heading_deg": math.nan})
        assert orch.grid_search.is_active is True
        assert all(math.isfinite(c) for wp in orch.grid_search.status().waypoints for c in wp)


def test_bad_max_speed_values_are_ignored_and_the_rest_still_applies(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        orch._on_mode_command({"mode": "follow", "follow_max_speed_mps": "fast", "follow_separation_m": 8.0})
        assert orch.follow.limits["target_separation_m"] == 8.0


def test_a_land_confirmation_nobody_asked_for_is_ignored(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.requested_mode = SupervisorState.FOLLOWING
        orch._on_land_confirmation_response({"approved": True})
        assert all(c.args[2] != 9 for c in conn.mav.set_mode_send.call_args_list)  # LAND never sent
        assert orch.requested_mode == SupervisorState.FOLLOWING


@pytest.mark.asyncio
async def test_target_recovery_rtl_is_not_sent_after_the_pilot_left_guided(tmp_path):
    """A pilot's FLTMODE_CH switch to LOITER is not stick override, but the
    search timer kept running and used to RTL them anyway."""
    from companion.tests.test_target_recovery_orchestrator import _build_orchestrator, _engage_follow

    with _build_orchestrator(tmp_path) as (orch, recorder, conn, _transport):
        await _engage_follow(orch)
        orch.mavlink.telemetry.battery_remaining_pct = 80
        orch.mavlink.telemetry.fc_mode = "LOITER"
        ts = 0.1
        for _ in range(10):
            await orch.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05
        assert all(c.args[2] != 6 for c in conn.mav.set_mode_send.call_args_list)  # RTL never sent
        recorder.close()
