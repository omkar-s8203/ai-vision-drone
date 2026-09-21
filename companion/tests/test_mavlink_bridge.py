from unittest.mock import patch

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
    bridge never listened for COMMAND_ACK, so the rejection was otherwise
    invisible - reported live as "the app's DISARM button does nothing").
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
