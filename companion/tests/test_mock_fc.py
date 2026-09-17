import asyncio

import pytest

from companion.mavlink.bridge import MavlinkBridge
from companion.tests.conftest import wait_until
from sim.mock_fc import MockFlightController

TEST_FC_PORT = 14720
TEST_BRIDGE_PORT = 14721


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
