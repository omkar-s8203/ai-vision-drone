"""Tests for MavlinkBridge.run()'s exception isolation - a real robustness
gap found in a code-review audit: _handle_message()/on_message() used to run
with no exception handling inside the while True receive loop (a background
asyncio task per main.py's start()), so a single bad/unexpected MAVLink
message would silently and permanently kill all telemetry/heartbeat
processing for the rest of the session. Same class of bug already fixed in
ws_server.py's _dispatch() and main.py's _perception_loop()."""

from unittest.mock import MagicMock, patch

import pytest

from companion.mavlink.bridge import MavlinkBridge


class _StopLoop(BaseException):
    """Sentinel raised from a mocked recv_match() to end run()'s otherwise-
    infinite while True loop once the test has seen enough messages. A
    BaseException: run() treats an ordinary read Exception as a lost link and
    reconnects (see test_mavlink_reconnect.py)."""


def _make_msg(msg_type: str) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = msg_type
    return msg


@pytest.mark.asyncio
async def test_a_raising_on_message_callback_does_not_kill_the_receive_loop():
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = bridge._conn
        conn.target_system = 1
        conn.target_component = 1

        bad_msg = _make_msg("UNKNOWN_TYPE_FOR_TEST")
        good_msg = _make_msg("UNKNOWN_TYPE_FOR_TEST")
        conn.recv_match.side_effect = [bad_msg, good_msg, _StopLoop()]

        received = []

        def on_message(msg):
            if msg is bad_msg:
                raise ValueError("boom - simulates a bug in a message callback")
            received.append(msg)

        with pytest.raises(_StopLoop):
            await bridge.run(on_message=on_message)

        assert received == [good_msg]


@pytest.mark.asyncio
async def test_a_message_that_makes_handle_message_raise_does_not_kill_the_loop():
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = bridge._conn
        conn.target_system = 1
        conn.target_component = 1

        bad_msg = MagicMock()
        bad_msg.get_type.side_effect = RuntimeError("boom - malformed message")
        good_msg = _make_msg("UNKNOWN_TYPE_FOR_TEST")
        conn.recv_match.side_effect = [bad_msg, good_msg, _StopLoop()]

        received = []

        with pytest.raises(_StopLoop):
            await bridge.run(on_message=received.append)

        assert received == [good_msg]
