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
