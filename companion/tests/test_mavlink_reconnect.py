"""MavlinkBridge link recovery. A lost link (USB FC unplugged or power-cycled,
a wedged serial port) used to end the receive task for good: the exception
went nowhere, telemetry froze and the heartbeat task died, until the whole
service was restarted. run() now reopens the link, and a failed write is
reported instead of thrown into the caller."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from companion.mavlink import bridge as bridge_module
from companion.mavlink.bridge import MavlinkBridge


class _StopLoop(BaseException):
    """Ends run() from a mocked recv_match(). A BaseException so run()'s own
    link-error handling (which catches Exception) does not treat it as a lost
    link and reconnect."""


@pytest.fixture(autouse=True)
def _no_reconnect_delay(monkeypatch):
    monkeypatch.setattr(bridge_module, "RECONNECT_MIN_DELAY_S", 0.0)


def _msg(msg_type: str) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = msg_type
    return msg


def _conn(recv_side_effect) -> MagicMock:
    conn = MagicMock()
    conn.target_system = 1
    conn.target_component = 1
    conn.recv_match.side_effect = recv_side_effect
    return conn


async def _run_until_stopped(bridge, on_message=None, timeout=3.0):
    with pytest.raises(_StopLoop):
        await asyncio.wait_for(bridge.run(on_message=on_message), timeout)


@pytest.mark.asyncio
async def test_a_read_error_reopens_the_link_and_receiving_resumes():
    first = _conn([OSError("device disconnected")])
    good = _msg("ATTITUDE_FOR_TEST")
    second = _conn([good, _StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.side_effect = [first, second]
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        received = []
        await _run_until_stopped(bridge, received.append)

    assert received == [good]
    assert bridge.reconnect_count == 1
    first.close.assert_called_once()
    assert bridge._conn is second


@pytest.mark.asyncio
async def test_reopening_keeps_retrying_while_the_port_cannot_be_opened():
    first = _conn([OSError("device disconnected")])
    second = _conn([_StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.side_effect = [
            first, OSError("no such device"), OSError("no such device"), second,
        ]
        bridge = MavlinkBridge("/dev/ttyACM0", reconnect_max_delay_s=0.0)
        bridge.connect()
        await _run_until_stopped(bridge)

    assert mavutil.mavlink_connection.call_count == 4
    assert bridge.reconnect_count == 1
    assert bridge._conn is second


def _silent_recv(**_kwargs):
    time.sleep(0.03)  # a real receive timeout, coarser than the Windows clock tick
    return None


@pytest.mark.asyncio
async def test_prolonged_silence_reopens_the_link():
    first = _conn(_silent_recv)
    second = _conn([_StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.side_effect = [first, second]
        bridge = MavlinkBridge("/dev/serial0", silence_reconnect_s=0.0)
        bridge.connect()
        await _run_until_stopped(bridge)

    assert bridge.reconnect_count == 1


@pytest.mark.asyncio
async def test_silence_shorter_than_the_limit_does_not_reopen():
    conn = _conn([None, None, _StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.return_value = conn
        bridge = MavlinkBridge("/dev/serial0", silence_reconnect_s=60.0)
        bridge.connect()
        await _run_until_stopped(bridge)

    assert bridge.reconnect_count == 0
    conn.close.assert_not_called()


@pytest.mark.asyncio
async def test_silence_reconnect_can_be_disabled():
    conn = _conn([None, None, _StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.return_value = conn
        bridge = MavlinkBridge("/dev/serial0", silence_reconnect_s=None)
        bridge.connect()
        await _run_until_stopped(bridge)

    assert bridge.reconnect_count == 0


@pytest.mark.asyncio
async def test_the_fc_streams_are_requested_again_after_a_reconnect():
    """A new connection - or an FC that rebooted - knows nothing of the
    streams this link asked for."""
    first = _conn([_msg("HEARTBEAT"), OSError("device disconnected")])
    second = _conn([_msg("HEARTBEAT"), _StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.side_effect = [first, second]
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        await _run_until_stopped(bridge)

    first.mav.request_data_stream_send.assert_called_once()
    second.mav.request_data_stream_send.assert_called_once()


def test_a_failed_velocity_write_reports_false_instead_of_raising():
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        bridge._conn.mav.set_position_target_local_ned_send.side_effect = OSError("write failed")
        assert bridge.send_velocity_setpoint(1.0, 0.0, 0.0, 0.0, guidance_allowed=True) is False
        assert bridge._link_error is not None


def test_a_successful_velocity_write_reports_true():
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        assert bridge.send_velocity_setpoint(1.0, 0.0, 0.0, 0.0, guidance_allowed=True) is True
        assert bridge._link_error is None


@pytest.mark.asyncio
async def test_a_failed_write_makes_run_reopen_the_link():
    first = _conn([None] * 50)
    second = _conn([_StopLoop()])
    with patch("companion.mavlink.bridge.mavutil") as mavutil:
        mavutil.mavlink_connection.side_effect = [first, second]
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        first.mav.set_position_target_local_ned_send.side_effect = OSError("write failed")
        bridge.send_velocity_setpoint(1.0, 0.0, 0.0, 0.0, guidance_allowed=True)
        await _run_until_stopped(bridge)

    assert bridge.reconnect_count == 1
    assert bridge._link_error is None


def test_an_arm_request_that_could_not_be_sent_is_reported_rejected():
    """No ACK will ever come for a request that never left the Pi - the
    operator hears about it now instead of waiting on nothing."""
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        bridge._conn.mav.command_long_send.side_effect = OSError("write failed")
        bridge.arm(True)
    assert bridge.pending_arm_ack == {"armed_requested": True, "accepted": False}
    assert bridge._pending_arm_intents == []


def test_a_mode_request_that_could_not_be_sent_is_still_retried():
    """Handled like a lost packet: check_pending_mode() re-sends it."""
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        bridge._conn.mav.set_mode_send.side_effect = OSError("write failed")
        assert bridge.set_mode("LOITER") is True
        bridge._conn.mav.set_mode_send.side_effect = None
        bridge.check_pending_mode(now=bridge._pending_mode["sent_ts"] + 10.0)
    assert bridge._conn.mav.set_mode_send.call_count == 2


@pytest.mark.asyncio
async def test_the_heartbeat_task_survives_write_errors():
    """A raising heartbeat_send() used to kill the companion's own heartbeat
    for the rest of the session."""
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("/dev/ttyACM0")
        bridge.connect()
        bridge._conn.mav.heartbeat_send.side_effect = OSError("write failed")
        task = asyncio.create_task(bridge._own_heartbeat_loop(rate_hz=100.0))
        await asyncio.sleep(0.05)
        assert not task.done()
        assert bridge._conn.mav.heartbeat_send.call_count > 1
        task.cancel()
