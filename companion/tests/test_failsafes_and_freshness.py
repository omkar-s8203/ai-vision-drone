import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.follow import FollowController
from companion.guidance.grid_search import GridSearchController
from companion.guidance.orbit import OrbitController
from companion.mavlink.bridge import MavlinkBridge
from companion.safety.supervisor import (
    REQUIRED_SUBSYSTEMS,
    SafetySupervisor,
    SupervisorInputs,
    SupervisorState,
)
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tests.test_tracking_safety_orchestrator import _build, _frame, _person
from companion.tracking.base import TrackedTarget
from companion.tracking.state import TrackingState
from companion.vision.detector import BBox, IMX500Detector

IMAGE_W, IMAGE_H = 1280, 720


def _only_stops_since(conn, count_before):
    """Every velocity setpoint sent after `count_before` is a zero-velocity stop."""
    calls = conn.mav.set_position_target_local_ned_send.call_args_list[count_before:]
    return all(c.args[8:11] == (0.0, 0.0, 0.0) and c.args[15] == 0.0 for c in calls)


# --- operator link liveness: real traffic, not socket state ----------------

class _AgingTransport(FakeTransport):
    def __init__(self, age_s):
        super().__init__(connected=True)
        self.age_s = age_s

    def seconds_since_last_message(self):
        return self.age_s


def test_a_silent_client_is_treated_as_disconnected_even_with_an_open_socket():
    link = GroundStationLink(_AgingTransport(age_s=5.0), comms_timeout_s=3.0)
    assert link.is_connected is False


def test_a_recently_heard_client_is_connected():
    link = GroundStationLink(_AgingTransport(age_s=0.4), comms_timeout_s=3.0)
    assert link.is_connected is True


def test_no_socket_is_disconnected_regardless_of_traffic_age():
    transport = _AgingTransport(age_s=0.0)
    transport.has_clients = False
    assert GroundStationLink(transport, comms_timeout_s=3.0).is_connected is False


def test_without_a_timeout_only_socket_state_matters():
    assert GroundStationLink(_AgingTransport(age_s=999.0)).is_connected is True


def test_real_transport_tracks_the_time_of_the_last_message():
    from companion.comms.transport import WebSocketTransport

    transport = WebSocketTransport("127.0.0.1", 0)
    assert transport.seconds_since_last_message() < 1.0
    transport._last_rx -= 10.0
    assert transport.seconds_since_last_message() >= 10.0


# --- FC telemetry freshness and stream re-request --------------------------

def _bridge():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14780")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED = 128
        return bridge, conn, mock_mavutil


def _heartbeat():
    msg = MagicMock()
    msg.get_type.return_value = "HEARTBEAT"
    msg.get_srcSystem.return_value = 1
    msg.get_srcComponent.return_value = 1
    msg.base_mode = 0
    return msg


def _position(rel_alt_mm=10_000):
    msg = MagicMock()
    msg.get_type.return_value = "GLOBAL_POSITION_INT"
    msg.lat, msg.lon, msg.relative_alt, msg.vx, msg.vy = 377_749_000, -1_224_194_000, rel_alt_mm, 0, 0
    return msg


def test_position_is_unknown_until_a_position_message_arrives():
    bridge, _conn, _m = _bridge()
    assert bridge.fresh_alt_m() is None
    assert bridge.fresh_position() is None


def test_fresh_position_and_altitude_after_a_message():
    bridge, _conn, _m = _bridge()
    bridge._handle_message(_position(12_500))
    assert bridge.fresh_alt_m() == pytest.approx(12.5)
    assert bridge.fresh_position() == pytest.approx((37.7749, -122.4194))


def test_stale_position_reads_as_unknown_not_as_the_last_value():
    bridge, _conn, _m = _bridge()
    bridge._handle_message(_position())
    bridge.telemetry.position_ts -= 10.0
    assert bridge.fresh_alt_m() is None
    assert bridge.fresh_position() is None
    assert bridge.telemetry.alt_m == 10.0  # the raw last value is still there for display


def test_streams_are_requested_again_when_position_goes_stale_but_heartbeats_continue():
    """An FC that rebooted mid-session keeps heartbeating but forgets every
    stream request - without a re-request, altitude/GPS freeze forever."""
    bridge, conn, _m = _bridge()
    bridge._handle_message(_heartbeat())
    assert conn.mav.request_data_stream_send.call_count == 1

    bridge._handle_message(_position())
    bridge._handle_message(_heartbeat())  # position is fresh -> no re-request
    assert conn.mav.request_data_stream_send.call_count == 1

    bridge.telemetry.position_ts -= 10.0  # the stream has silently stopped
    bridge._last_stream_request_ts -= 10.0
    bridge._handle_message(_heartbeat())
    assert conn.mav.request_data_stream_send.call_count == 2


def test_stream_re_requests_are_rate_limited():
    bridge, conn, _m = _bridge()
    bridge._handle_message(_heartbeat())
    for _ in range(10):
        bridge._handle_message(_heartbeat())  # position never arrives, but not every second
    assert conn.mav.request_data_stream_send.call_count == 1


# --- supervisor: geofence and battery gate every mode ----------------------

def _supervisor():
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    for name in REQUIRED_SUBSYSTEMS:
        watchdog.beat(name)
    return SafetySupervisor(watchdog)


def _inputs(**overrides):
    base = dict(
        fc_mode="GUIDED", ai_guidance_mode_name="GUIDED", rc_override_active=False,
        tracking_state=TrackingState.TRACKING, comms_alive=True, requested_state=SupervisorState.FOLLOWING,
    )
    base.update(overrides)
    return SupervisorInputs(**base)


@pytest.mark.parametrize("mode", [SupervisorState.FOLLOWING, SupervisorState.ORBITING, SupervisorState.GRID_SEARCH])
def test_a_geofence_breach_stops_every_guidance_mode(mode):
    decision = _supervisor().evaluate(_inputs(requested_state=mode, fence_breached=True))
    assert decision.state == SupervisorState.SAFE
    assert decision.reason == "geofence_breached"
    assert decision.guidance_allowed is False


def test_approach_test_keeps_its_own_sticky_fence_abort():
    """Approach-Test must still see the breach itself (a sticky abort) rather
    than being forced SAFE and quietly resuming once the fence clears."""
    decision = _supervisor().evaluate(_inputs(requested_state=SupervisorState.APPROACHING, fence_breached=True))
    assert decision.state == SupervisorState.APPROACHING


def test_a_critically_low_battery_stops_guidance():
    decision = _supervisor().evaluate(_inputs(battery_critical=True))
    assert decision.state == SupervisorState.SAFE
    assert decision.reason == "battery_critical"


def test_normal_inputs_are_unaffected():
    assert _supervisor().evaluate(_inputs()).guidance_allowed is True


# --- Pi-side failsafe RTL --------------------------------------------------

def _rtl_calls(conn):
    # ArduCopter RTL = custom mode 6; set_mode_send(target_system, flag, mode_number)
    return [c for c in conn.mav.set_mode_send.call_args_list if c.args[-1] == 6]


@pytest.mark.asyncio
async def test_comms_loss_for_long_enough_requests_rtl_once(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.link.transport.has_clients = False
        await orch.process_frame(_frame(0.0, []))
        await orch.process_frame(_frame(10.0, []))
        assert _rtl_calls(conn) == []  # not yet: comms_loss_rtl_s is 15s
        await orch.process_frame(_frame(16.0, []))
        assert len(_rtl_calls(conn)) == 1
        await orch.process_frame(_frame(20.0, []))
        await orch.process_frame(_frame(30.0, []))
        assert len(_rtl_calls(conn)) == 1  # one request per episode, not one per frame


@pytest.mark.asyncio
async def test_a_brief_comms_dropout_never_triggers_rtl(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.link.transport.has_clients = False
        await orch.process_frame(_frame(0.0, []))
        await orch.process_frame(_frame(5.0, []))
        orch.link.transport.has_clients = True
        await orch.process_frame(_frame(6.0, []))
        orch.link.transport.has_clients = False
        await orch.process_frame(_frame(7.0, []))
        await orch.process_frame(_frame(20.0, []))  # only 13s into the second dropout
        assert _rtl_calls(conn) == []


@pytest.mark.asyncio
async def test_failsafe_rtl_is_suppressed_while_the_pilot_has_rc_override(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.rc_channels = {1: 2000, 2: 1500, 3: 1500, 4: 1500}  # roll deflected
        orch.link.transport.has_clients = False
        await orch.process_frame(_frame(0.0, []))
        await orch.process_frame(_frame(20.0, []))
        assert _rtl_calls(conn) == []


@pytest.mark.asyncio
async def test_failsafe_rtl_only_when_this_pi_is_holding_the_aircraft(tmp_path):
    """Not armed, or already in some other mode (the pilot's own choice):
    never change the mode."""
    with _build(tmp_path) as (orch, _rec, conn):
        orch.link.transport.has_clients = False
        orch.mavlink.telemetry.fc_mode = "LOITER"
        await orch.process_frame(_frame(0.0, []))
        await orch.process_frame(_frame(20.0, []))
        orch.mavlink.telemetry.fc_mode = "GUIDED"
        orch.mavlink.telemetry.armed = False
        await orch.process_frame(_frame(40.0, []))
        assert _rtl_calls(conn) == []


@pytest.mark.asyncio
async def test_critical_battery_requests_rtl_and_stops_guidance(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.battery_remaining_pct = 15
        result = await orch.process_frame(_frame(0.0, []))
        assert len(_rtl_calls(conn)) == 1
        assert orch.requested_mode == SupervisorState.IDLE
        assert result is not None


@pytest.mark.asyncio
async def test_rtl_is_not_re_fired_after_the_pilot_takes_the_mode_back(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.battery_remaining_pct = 15
        await orch.process_frame(_frame(0.0, []))
        orch.mavlink.telemetry.fc_mode = "LOITER"     # pilot took over
        await orch.process_frame(_frame(1.0, []))
        orch.mavlink.telemetry.fc_mode = "GUIDED"     # ...and later chose GUIDED again themselves
        await orch.process_frame(_frame(2.0, []))
        assert len(_rtl_calls(conn)) == 1


@pytest.mark.asyncio
async def test_unknown_battery_never_triggers_anything(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        assert orch.mavlink.telemetry.battery_remaining_pct is None
        await orch.process_frame(_frame(0.0, []))
        assert _rtl_calls(conn) == []


@pytest.mark.asyncio
async def test_the_geofence_stops_follow_at_the_orchestrator_level(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        person = _person(BBox(300, 300, 80, 160))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_mode_command({"mode": "follow"})
        await orch.process_frame(_frame(0.1, [person]))
        sent_before = conn.mav.set_position_target_local_ned_send.call_count
        assert sent_before > 0
        orch.mavlink.telemetry.fence_breached = True
        await orch.process_frame(_frame(0.2, [person]))
        # No more guidance - only an explicit stop, so the FC does not keep
        # flying the last velocity for its 3 s GUIDED timeout.
        assert _only_stops_since(conn, sent_before)


# --- auto-takeoff pre-flight ------------------------------------------------

async def _armed_and_guided_with_takeoff_requested(orch):
    orch.mavlink.telemetry.alt_m = 0.0
    orch.mavlink.telemetry.position_ts = time.monotonic()
    person = _person(BBox(300, 300, 80, 160))
    orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
    await orch.process_frame(_frame(0.0, [person]))
    orch._on_mode_command({"mode": "follow", "auto_takeoff": True})
    await orch.process_frame(_frame(0.1, [person]))


def _takeoff_commands(conn):
    return [c for c in conn.mav.command_long_send.call_args_list if c.args[-1] == 10.0]


@pytest.mark.asyncio
async def test_takeoff_is_refused_on_a_bad_gps_fix(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.gps_fix_type = 1  # no 3D fix
        await _armed_and_guided_with_takeoff_requested(orch)
        assert _takeoff_commands(conn) == []
        assert orch.requested_mode == SupervisorState.IDLE
        assert orch.auto_takeoff.is_active is False
        assert _last_update(orch)["guidance_hold"] == "takeoff_refused_gps"


@pytest.mark.asyncio
async def test_takeoff_is_refused_on_a_low_battery(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.battery_remaining_pct = 25
        await _armed_and_guided_with_takeoff_requested(orch)
        assert _takeoff_commands(conn) == []
        assert _last_update(orch)["guidance_hold"] == "takeoff_refused_battery"


@pytest.mark.asyncio
async def test_takeoff_proceeds_when_gps_and_battery_are_good_or_not_yet_reported(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.gps_fix_type = 3
        orch.mavlink.telemetry.battery_remaining_pct = 80
        await _armed_and_guided_with_takeoff_requested(orch)
        assert len(_takeoff_commands(conn)) == 1
    with _build(tmp_path / "unknown") as (orch, _rec, conn):
        await _armed_and_guided_with_takeoff_requested(orch)  # nothing reported: the FC decides
        assert len(_takeoff_commands(conn)) == 1


@pytest.mark.asyncio
async def test_the_refusal_clears_on_the_next_mode_command(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.gps_fix_type = 1
        await _armed_and_guided_with_takeoff_requested(orch)
        orch._on_mode_command({"mode": "idle"})
        await orch.process_frame(_frame(0.5, []))
        assert _last_update(orch)["guidance_hold"] is None


def _last_update(orch):
    import json

    for raw in reversed(orch.link.transport.sent):
        msg = json.loads(raw)
        if msg["type"] == "tracking_update":
            return msg["payload"]
    raise AssertionError("no tracking_update")


# --- grid search: GPS-dependent, so it needs a good, fresh fix --------------

def _grid_ready(orch):
    orch.mavlink.telemetry.lat, orch.mavlink.telemetry.lon = 37.7749, -122.4194
    orch.mavlink.telemetry.heading_deg = 0.0
    orch.mavlink.telemetry.position_ts = time.monotonic()
    orch.mavlink.telemetry.gps_fix_type = 3
    orch.mavlink.telemetry.hdop = 1.0


GRID = {"mode": "grid_search", "grid_search_width_m": 60.0, "grid_search_height_m": 30.0}


@pytest.mark.parametrize("fix_type,hdop", [(None, None), (2, 1.0), (3, 5.0)])
def test_grid_search_refuses_to_start_on_a_missing_or_degraded_fix(tmp_path, fix_type, hdop):
    with _build(tmp_path) as (orch, _rec, _conn):
        _grid_ready(orch)
        orch.mavlink.telemetry.gps_fix_type = fix_type
        orch.mavlink.telemetry.hdop = hdop
        orch._on_mode_command(GRID)
        assert orch.grid_search.is_active is False
        assert orch.requested_mode == SupervisorState.IDLE


def test_grid_search_starts_on_a_good_fix(tmp_path):
    with _build(tmp_path) as (orch, _rec, _conn):
        _grid_ready(orch)
        orch._on_mode_command(GRID)
        assert orch.grid_search.is_active is True


@pytest.mark.asyncio
async def test_a_stale_position_holds_the_sweep_instead_of_steering_on_old_coordinates(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        _grid_ready(orch)
        orch._on_mode_command(GRID)
        await orch.process_frame(_frame(0.0, []))
        await orch.process_frame(_frame(0.1, []))
        assert conn.mav.set_position_target_local_ned_send.call_count > 0
        sent = conn.mav.set_position_target_local_ned_send.call_count

        orch.mavlink.telemetry.position_ts -= 30.0  # GLOBAL_POSITION_INT stopped
        await orch.process_frame(_frame(0.2, []))
        assert _only_stops_since(conn, sent)
        assert _last_update(orch)["guidance_hold"] == "gps_degraded"


@pytest.mark.asyncio
async def test_losing_the_gps_fix_mid_sweep_holds_it(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        _grid_ready(orch)
        orch._on_mode_command(GRID)
        await orch.process_frame(_frame(0.0, []))
        orch.mavlink.telemetry.gps_fix_type = 1
        sent = conn.mav.set_position_target_local_ned_send.call_count
        await orch.process_frame(_frame(0.1, []))
        assert conn.mav.set_position_target_local_ned_send.call_count == sent
        assert _last_update(orch)["guidance_hold"] == "gps_degraded"


# --- a stalled frame loop --------------------------------------------------

@pytest.mark.asyncio
async def test_a_stalled_frame_loop_restarts_controllers_from_a_standstill(tmp_path):
    """A multi-second gap between frames must not feed a huge dt into the
    acceleration limiter (a bigger allowed velocity step) or PID derivative."""
    with _build(tmp_path) as (orch, _rec, conn):
        person = _person(BBox(300, 300, 80, 160))
        orch._on_target_selected({"x": 340.0, "y": 380.0, "point": True})
        await orch.process_frame(_frame(0.0, [person]))
        orch._on_mode_command({"mode": "follow"})
        for i in range(1, 30):
            await orch.process_frame(_frame(0.1 * i, [person]))
        cruising = conn.mav.set_position_target_local_ned_send.call_args_list[-1].args[8]
        assert cruising > 0.5

        await orch.process_frame(_frame(20.0, [person]))       # 17 second stall
        stalled = conn.mav.set_position_target_local_ned_send.call_args_list[-1].args[8]
        assert stalled == 0.0
        await orch.process_frame(_frame(20.1, [person]))
        resumed = conn.mav.set_position_target_local_ned_send.call_args_list[-1].args[8]
        assert resumed <= orch.follow.limits["max_accel_mps2"] * 0.1 + 1e-9


# --- blind retreat is capped ----------------------------------------------

def _target(cx=IMAGE_W / 2, cy=IMAGE_H / 2):
    return TrackedTarget(
        target_id=1, bbox=BBox(cx - 25, cy - 50, 50, 100), confidence=0.9,
        class_id=0, class_name="person", last_seen_ts=0.0,
    )


def test_follow_retreat_is_capped_below_the_forward_limit():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    cmd = None
    for _ in range(80):
        cmd = controller.compute(_target(), distance_m=0.5, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == pytest.approx(-limits["max_reverse_speed_mps"])
    assert limits["max_reverse_speed_mps"] < limits["max_speed_mps"]


def test_follow_forward_speed_is_not_affected_by_the_reverse_cap():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    cmd = None
    for _ in range(80):
        cmd = controller.compute(_target(), distance_m=80.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == pytest.approx(limits["max_speed_mps"])


def test_orbit_retreat_is_capped_too():
    limits = load_yaml("orbit_limits.yaml")
    controller = OrbitController(limits)
    cmd = None
    for _ in range(80):
        cmd = controller.compute(_target(), distance_m=0.5, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps >= -limits["max_reverse_speed_mps"] - 1e-9


# --- grid search controller: ramp + altitude limits ------------------------

def _grid_controller(**extra):
    limits = load_yaml("grid_search_limits.yaml")
    limits.update(extra)
    controller = GridSearchController(limits)
    controller.start(37.7749, -122.4194, 100.0, 40.0, heading_deg=0.0)
    return controller, limits


def test_grid_search_forward_speed_ramps_instead_of_stepping():
    controller, limits = _grid_controller()
    first = controller.compute(37.7749, -122.4194, 90.0, 10.0, 0.1)  # facing east, the first leg
    assert first.vx_mps == pytest.approx(limits["max_accel_mps2"] * 0.1)


def test_grid_search_never_descends_through_the_floor():
    controller, limits = _grid_controller(search_altitude_m=1.0)  # asked to fly below the floor
    for _ in range(20):
        cmd = controller.compute(37.7749, -122.4194, 90.0, limits["min_altitude_m"], 0.1)
        assert cmd.vz_mps <= 0.0


def test_grid_search_holds_vertical_without_altitude_telemetry():
    controller, limits = _grid_controller(search_altitude_m=10.0)
    cmd = controller.compute(37.7749, -122.4194, 90.0, None, 0.1)
    assert cmd.vz_mps == 0.0


# --- detector: degenerate boxes never reach tracking -----------------------

class _FakeImx500:
    def __init__(self, boxes_px):
        self.boxes_px = list(boxes_px)

    def convert_inference_coords(self, box, metadata, picam2):
        return self.boxes_px.pop(0)


def _raw(boxes_px):
    n = len(boxes_px)
    outputs = [
        np.zeros((1, n, 4)), np.full((1, n), 0.9), np.zeros((1, n)), np.array([[n]]),
    ]
    return (_FakeImx500(boxes_px), outputs, None, None)


def test_non_finite_or_degenerate_boxes_are_dropped():
    detector = IMX500Detector(class_names=["person"], score_threshold=0.5)
    nan = float("nan")
    raw = _raw([(10, 10, 50, 100), (nan, 10, 50, 100), (10, 10, 0, 100), (10, 10, 50, float("inf")), (5, 5, 1, 1)])
    detections = detector.parse(raw, 0.0)
    assert [d.bbox for d in detections] == [BBox(10.0, 10.0, 50.0, 100.0)]


# --- a forced disarm cannot drop a flying aircraft --------------------------

def _arm_calls(conn):
    return conn.mav.command_long_send.call_args_list


def test_force_disarm_is_refused_while_airborne(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.alt_m = 12.0
        orch.mavlink.telemetry.position_ts = time.monotonic()
        orch._on_arm_command({"armed": False, "force": True})
        assert _arm_calls(conn) == []
        # ...and the operator is told it was rejected, like any refused disarm.
        assert orch.mavlink.pending_arm_ack == {"armed_requested": False, "accepted": False}


def test_force_disarm_is_allowed_on_the_ground(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.alt_m = 0.2
        orch.mavlink.telemetry.position_ts = time.monotonic()
        orch._on_arm_command({"armed": False, "force": True})
        assert len(_arm_calls(conn)) == 1


def test_force_disarm_with_unknown_altitude_is_allowed_bench_case(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.position_ts = None
        orch._on_arm_command({"armed": False, "force": True})
        assert len(_arm_calls(conn)) == 1


def test_a_normal_disarm_and_arm_are_never_blocked_by_altitude(tmp_path):
    """An unforced disarm is the FC's own decision (it refuses in flight itself);
    arming has nothing to do with this guard."""
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.alt_m = 12.0
        orch.mavlink.telemetry.position_ts = time.monotonic()
        orch._on_arm_command({"armed": False})
        orch._on_arm_command({"armed": True})
        assert len(_arm_calls(conn)) == 2


def test_bbox_order_xy_swaps_a_retrained_models_coordinates_before_conversion():
    seen = []

    class _Imx:
        def convert_inference_coords(self, box, metadata, picam2):
            seen.append(box)                     # what the firmware helper is asked to convert: (y0, x0, y1, x1)
            y0, x0, y1, x1 = box
            return (x0 * 1000, y0 * 1000, (x1 - x0) * 1000, (y1 - y0) * 1000)

    boxes = np.array([[[0.10, 0.20, 0.50, 0.60]]])   # a model emitting (x0, y0, x1, y1)
    raw = (_Imx(), [boxes, np.array([[0.9]]), np.array([[0.0]]), np.array([[1]])], None, None)

    IMX500Detector(class_names=["thing"], bbox_order="xy").parse(raw, 0.0)
    assert seen == [(0.20, 0.10, 0.60, 0.50)]        # swapped into (y0, x0, y1, x1)

    seen.clear()
    IMX500Detector(class_names=["thing"], bbox_order="yx").parse(raw, 0.0)
    assert seen == [(0.10, 0.20, 0.50, 0.60)]        # default: untouched


def test_an_unknown_bbox_order_is_rejected():
    with pytest.raises(ValueError):
        IMX500Detector(class_names=["thing"], bbox_order="wh")
