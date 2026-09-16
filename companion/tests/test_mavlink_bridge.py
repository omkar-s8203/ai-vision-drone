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
