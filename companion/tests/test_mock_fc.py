import asyncio

import pytest

from companion.mavlink.bridge import MavlinkBridge
from companion.tests.conftest import wait_until
from sim.mock_fc import MockFlightController

TEST_FC_PORT = 14720
TEST_BRIDGE_PORT = 14721
FENCE_FC_PORT = 14722
FENCE_BRIDGE_PORT = 14723
HOME_FC_PORT = 14724
HOME_BRIDGE_PORT = 14725
GPS_FC_PORT = 14726
GPS_BRIDGE_PORT = 14727


@pytest.mark.asyncio
async def test_mock_fc_reflects_real_arm_and_set_mode_commands_over_real_mavlink():
    """MockFlightController previously only understood
    SET_POSITION_TARGET_LOCAL_NED (guidance setpoints) - it silently
    ignored MavlinkBridge.arm()/set_mode(), so no integration test could
    verify those administrative commands actually reach the FC, only that
    MavlinkBridge constructed the right MAVLink message in isolation (see
    test_mavlink_bridge.py's mocked tests). This exercises the real chain:
    a real MavlinkBridge sending real COMMAND_LONG/SET_MODE messages over
    real UDP to a real (mock) flight controller.

    Both sides run their own background receive loop (mock_fc.run(),
    mavlink.run()) because pymavlink's UDP "server" sockets only learn a
    peer's address after actually receiving something from it - a
    one-shot connect()+prime_udp_peer() alone isn't enough for the bridge's
    own sends to reach the mock FC; the mock FC must send at least one
    heartbeat back first (see prime_udp_peer's docstring for the full
    Windows UDP address-learning story this project already worked through
    once during hardware bring-up).
    """
    mock_fc = MockFlightController(f"udpin:127.0.0.1:{TEST_FC_PORT}")
    mock_fc.set_mode("GUIDED")
    fc_task = asyncio.create_task(mock_fc.run(rate_hz=20.0))

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{TEST_BRIDGE_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", TEST_FC_PORT)
    mavlink_task = asyncio.create_task(mavlink.run(on_message=lambda _msg: None))

    try:
        await wait_until(lambda: mavlink.telemetry.fc_mode == "GUIDED", timeout=3.0)

        assert mock_fc.armed is False
        mavlink.arm(True)
        await wait_until(lambda: mock_fc.armed is True, timeout=2.0)

        mavlink.arm(False)
        await wait_until(lambda: mock_fc.armed is False, timeout=2.0)

        mavlink.set_mode("RTL")
        await wait_until(lambda: mock_fc.fc_mode == "RTL", timeout=2.0)
    finally:
        fc_task.cancel()
        mavlink_task.cancel()
        await asyncio.gather(fc_task, mavlink_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_bridge_reflects_a_real_geofence_breach_over_real_mavlink():
    """companion/main.py previously hardcoded geofence_breached=False -
    Approach-Test's geofence abort was fully unit-tested at the controller
    level but never actually wired to a real signal (see docs/safety-case.md
    before this landed). This exercises the real chain in the other
    direction from the test above: a real SYS_STATUS message from a (mock)
    FC, over real UDP, correctly parsed into MavlinkBridge.telemetry.
    fence_breached using pymavlink's own MAV_SYS_STATUS_GEOFENCE bit
    constant, not a guessed bit shift."""
    mock_fc = MockFlightController(f"udpin:127.0.0.1:{FENCE_FC_PORT}")
    fc_task = asyncio.create_task(mock_fc.run(rate_hz=20.0))

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{FENCE_BRIDGE_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", FENCE_FC_PORT)
    mavlink_task = asyncio.create_task(mavlink.run(on_message=lambda _msg: None))

    try:
        await wait_until(lambda: mavlink.telemetry.last_heartbeat_ts is not None, timeout=3.0)
        assert mavlink.telemetry.fence_enabled is False
        assert mavlink.telemetry.fence_breached is False

        mock_fc.set_fence_state(enabled=True, breached=False)
        await wait_until(lambda: mavlink.telemetry.fence_enabled is True, timeout=2.0)
        assert mavlink.telemetry.fence_breached is False  # enabled but healthy

        mock_fc.set_fence_state(enabled=True, breached=True)
        await wait_until(lambda: mavlink.telemetry.fence_breached is True, timeout=2.0)

        mock_fc.set_fence_state(enabled=False)
        await wait_until(lambda: mavlink.telemetry.fence_enabled is False, timeout=2.0)
        assert mavlink.telemetry.fence_breached is False
    finally:
        fc_task.cancel()
        mavlink_task.cancel()
        await asyncio.gather(fc_task, mavlink_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_bridge_receives_real_home_position_on_request():
    """companion/guidance/target_recovery.py's RTL-vs-land decision needs a
    real distance-to-home estimate, which needs HOME_POSITION -
    MavlinkBridge.request_home_position() sends a real
    MAV_CMD_GET_HOME_POSITION over real MAVLink, and this proves a real
    (mock) FC's real HOME_POSITION reply is correctly parsed into
    telemetry.home_lat/home_lon, using pymavlink's own confirmed
    home_position_send() signature - not guessed field order."""
    mock_fc = MockFlightController(f"udpin:127.0.0.1:{HOME_FC_PORT}")
    fc_task = asyncio.create_task(mock_fc.run(rate_hz=20.0))

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{HOME_BRIDGE_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", HOME_FC_PORT)
    mavlink_task = asyncio.create_task(mavlink.run(on_message=lambda _msg: None))

    try:
        await wait_until(lambda: mavlink.telemetry.last_heartbeat_ts is not None, timeout=3.0)
        assert mavlink.telemetry.home_lat is None
        assert mavlink.telemetry.home_lon is None

        mock_fc.set_home(lat=37.7749, lon=-122.4194)
        mavlink.request_home_position()

        await wait_until(lambda: mavlink.telemetry.home_lat is not None, timeout=2.0)
        assert mavlink.telemetry.home_lat == pytest.approx(37.7749, abs=1e-6)
        assert mavlink.telemetry.home_lon == pytest.approx(-122.4194, abs=1e-6)
    finally:
        fc_task.cancel()
        mavlink_task.cancel()
        await asyncio.gather(fc_task, mavlink_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_bridge_reflects_real_gps_satellite_count_and_fix_type():
    """A real bug found from a UI review: the Android HUD's "SAT" readout
    was hardcoded to a fake "12" because nothing ever populated a real
    value - and the "GPS: FIX" indicator only inferred fix status from
    `lat` being non-null, a much less precise proxy than the FC's actual
    GPS_RAW_INT.fix_type. This proves both are parsed correctly from a
    real GPS_RAW_INT message over real MAVLink, using pymavlink's own
    confirmed gps_raw_int_send() signature, including the standard
    "satellites_visible=255 means unknown, not zero" sentinel."""
    mock_fc = MockFlightController(f"udpin:127.0.0.1:{GPS_FC_PORT}")
    fc_task = asyncio.create_task(mock_fc.run(rate_hz=20.0))

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{GPS_BRIDGE_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", GPS_FC_PORT)
    mavlink_task = asyncio.create_task(mavlink.run(on_message=lambda _msg: None))

    try:
        await wait_until(lambda: mavlink.telemetry.last_heartbeat_ts is not None, timeout=3.0)
        # MockFlightController defaults to a healthy 3D fix with 12 sats.
        await wait_until(lambda: mavlink.telemetry.satellites_visible is not None, timeout=2.0)
        assert mavlink.telemetry.satellites_visible == 12
        assert mavlink.telemetry.gps_fix_type == 3

        mock_fc.set_gps(fix_type=0, satellites_visible=0)
        await wait_until(lambda: mavlink.telemetry.gps_fix_type == 0, timeout=2.0)
        assert mavlink.telemetry.satellites_visible == 0

        mock_fc.set_gps(fix_type=3, satellites_visible=255)  # 255 = genuinely unknown
        await wait_until(lambda: mavlink.telemetry.gps_fix_type == 3, timeout=2.0)
        assert mavlink.telemetry.satellites_visible is None
    finally:
        fc_task.cancel()
        mavlink_task.cancel()
        await asyncio.gather(fc_task, mavlink_task, return_exceptions=True)
