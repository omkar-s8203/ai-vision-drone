from unittest.mock import MagicMock, patch

from companion.mavlink.bridge import MavlinkBridge


def test_connect_passes_baud_when_specified():
    """Real bug found during hardware bring-up: build_hardware_orchestrator
    read baud from hardware.yaml but never passed it through to pymavlink,
    so the bridge would silently connect at pymavlink's default baud
    instead of the configured one (docs plan M7 hardware notes)."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("/dev/serial0", baud=921600)
        bridge.connect()
        mock_mavutil.mavlink_connection.assert_called_once_with(
            "/dev/serial0", source_system=1, baud=921600
        )


def test_connect_omits_baud_when_not_specified():
    """UDP connections (sim mode) don't need an explicit baud - must not
    regress by always passing one."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        mock_mavutil.mavlink_connection.assert_called_once_with(
            "udpin:127.0.0.1:14550", source_system=1
        )


def test_arm_sends_component_arm_disarm_with_param1_one():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(True)

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0
        )


def test_disarm_sends_component_arm_disarm_with_param1_zero():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(False)

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0
        )


def test_request_data_streams_sends_request_data_stream_all():
    """A real bug found from a field report: the bridge only ever sent its
    own HEARTBEAT back and passively waited for the FC to stream everything
    else - HEARTBEAT is sent unconditionally by ArduPilot regardless of
    stream-rate config, but GLOBAL_POSITION_INT/ATTITUDE/VFR_HUD/
    RC_CHANNELS/SYS_STATUS/BATTERY_STATUS/GPS_RAW_INT are only streamed to a
    link that actually asked (the way a real GCS does on connect) - so a
    real bench test showed a healthy "Link: OK" (real HEARTBEAT parsing)
    with every other telemetry field stuck on "--" forever. This proves the
    real REQUEST_DATA_STREAM message (verified via pymavlink's own
    request_data_stream_send signature and MAV_DATA_STREAM_ALL constant,
    not guessed) is sent correctly."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mock_mavutil.mavlink.MAV_DATA_STREAM_ALL = 0
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.request_data_streams(rate_hz=4)

        conn.mav.request_data_stream_send.assert_called_once_with(1, 1, 0, 4, 1)


def test_force_disarm_sends_component_arm_disarm_with_documented_force_value():
    """A real bug this guards against: ArduCopter refuses an unforced
    (param2=0) disarm outright if its own land-detector believes the
    aircraft is flying - a bench test with props spinning can trip a false
    positive there, silently ignoring every normal disarm request (this
    bridge used to never listen for COMMAND_ACK, so the rejection was
    otherwise invisible - reported live as "the app's DISARM button does
    nothing"; see the COMMAND_ACK tests below for the fix).
    force=True must send MAV_CMD_COMPONENT_ARM_DISARM's own documented
    param2=21196 "force" value (confirmed via pymavlink's bundled command
    definitions, not guessed - see FORCE_ARM_DISARM_MAGIC_NUMBER)."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(False, force=True)

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 21196, 0, 0, 0, 0, 0
        )


def test_force_arm_never_bypasses_pre_arm_checks():
    """force is documented/reserved for the disarm-while-flying refusal
    only - arming must never set it, since pre-arm checks existing to be
    bypassed is exactly the danger this project's arm() docstring already
    commits to never doing."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(True, force=True)

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0
        )


def test_set_mode_sends_correct_custom_mode_number():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mock_mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1

        result = bridge.set_mode("loiter")  # case-insensitive

        assert result is True
        conn.mav.set_mode_send.assert_called_once_with(1, 1, 5)  # LOITER = 5


def test_set_mode_returns_false_for_unknown_mode():
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()

        assert bridge.set_mode("NOT_A_REAL_MODE") is False


def _fake_command_ack(command, result) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = "COMMAND_ACK"
    msg.command = command
    msg.result = result
    return msg


def test_arm_accepted_sets_pending_arm_ack():
    """A real, previously-documented gap: this bridge never listened for
    COMMAND_ACK at all, so arm()/disarm() acceptance or rejection was
    completely invisible to the app."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(True)
        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            mock_mavutil.mavlink.MAV_RESULT_ACCEPTED,
        ))

        assert bridge.pending_arm_ack == {"armed_requested": True, "accepted": True}
        assert bridge._pending_arm_intents == []  # consumed, not left stale


def test_arm_rejected_sets_pending_arm_ack_not_accepted():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(True)
        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            mock_mavutil.mavlink.MAV_RESULT_DENIED,
        ))

        assert bridge.pending_arm_ack == {"armed_requested": True, "accepted": False}


def test_disarm_rejected_reports_armed_requested_false():
    """A real field-reported bug this fixes: ArduCopter refusing an
    unforced disarm while it thinks it's flying used to be completely
    silent - "the app's DISARM button does nothing"."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(False)
        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            mock_mavutil.mavlink.MAV_RESULT_DENIED,
        ))

        assert bridge.pending_arm_ack == {"armed_requested": False, "accepted": False}


def test_command_ack_for_an_unrelated_command_is_ignored():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_GET_HOME_POSITION,
            mock_mavutil.mavlink.MAV_RESULT_ACCEPTED,
        ))

        assert bridge.pending_arm_ack is None


def test_command_ack_without_a_pending_arm_request_is_ignored():
    """A stray/duplicate COMMAND_ACK for arm/disarm arriving with no
    matching request in flight (already consumed, or never made) must not
    fabricate a result."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            mock_mavutil.mavlink.MAV_RESULT_ACCEPTED,
        ))

        assert bridge.pending_arm_ack is None


def test_rapid_arm_then_disarm_before_either_ack_arrives_is_not_misattributed():
    """A real bug a code-review audit caught: a single scalar tracking
    "the last requested intent" meant a rapid ARM-then-DISARM double-tap
    (or a slow/lossy link) before the first command's COMMAND_ACK arrived
    would overwrite the correlation state for the first request - that ACK
    then got misattributed to the second request, and the real second ACK
    (if it arrived at all) was silently dropped since the tracking state
    was already consumed. Both requests are in flight before either ACK
    arrives; each ACK must resolve to its own request, oldest first,
    matching the order ArduPilot actually processes and acks them in."""
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.arm(True)  # request 1: arm
        bridge.arm(False)  # request 2: disarm - sent before request 1's ack arrives

        # The FC acks them in the order it received them (request 1 first).
        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            mock_mavutil.mavlink.MAV_RESULT_ACCEPTED,  # the arm was accepted
        ))
        assert bridge.pending_arm_ack == {"armed_requested": True, "accepted": True}

        bridge._handle_message(_fake_command_ack(
            mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            mock_mavutil.mavlink.MAV_RESULT_DENIED,  # the disarm was rejected
        ))
        assert bridge.pending_arm_ack == {"armed_requested": False, "accepted": False}
        assert bridge._pending_arm_intents == []


def test_takeoff_sends_nav_takeoff_with_altitude_in_param7():
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        bridge = MavlinkBridge("udpin:127.0.0.1:14550")
        bridge.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1

        bridge.takeoff(10.0)

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, 10.0
        )
