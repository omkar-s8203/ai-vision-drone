from __future__ import annotations

import asyncio
import time

from pymavlink import mavutil

# ArduCopter custom_mode numbers (subset needed for testing).
COPTER_MODE_TO_NUMBER = {
    "STABILIZE": 0,
    "ALT_HOLD": 2,
    "AUTO": 3,
    "GUIDED": 4,
    "LOITER": 5,
    "RTL": 6,
}
COPTER_NUMBER_TO_MODE = {number: name for name, number in COPTER_MODE_TO_NUMBER.items()}


class MockFlightController:
    """Lightweight stand-in for ArduPilot SITL.

    Real SITL needs a Linux build environment (WSL2 on Windows) and isn't
    assumed to be available - see sim/README.md. This emulates just enough
    MAVLink (HEARTBEAT with a real ArduCopter mode number, RC_CHANNELS,
    GLOBAL_POSITION_INT) to exercise the companion MAVLink bridge, RC
    override detection, and safety supervisor end-to-end, and records any
    SET_POSITION_TARGET_LOCAL_NED setpoints it receives so tests can assert
    on what guidance actually sent.
    """

    def __init__(self, bind_address: str = "udpin:127.0.0.1:14550") -> None:
        self._conn = mavutil.mavlink_connection(
            bind_address, source_system=1, source_component=1
        )
        self.fc_mode = "STABILIZE"
        self.armed = False
        self.rc_override_active = False
        self.lat = 0.0
        self.lon = 0.0
        self.alt_m = 0.0
        self.received_setpoints: list[tuple[float, float, float, float]] = []

    def set_mode(self, mode: str) -> None:
        """Simulates the pilot's hardware mode switch changing the FC mode -
        in reality this never touches the Pi at all; here it just flips the
        mock's reported mode so the bridge/supervisor reaction can be tested."""
        self.fc_mode = mode

    def set_armed(self, armed: bool) -> None:
        self.armed = armed

    def set_rc_override(self, active: bool) -> None:
        self.rc_override_active = active

    def _send_heartbeat(self) -> None:
        base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        if self.armed:
            base_mode |= mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        self._conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_QUADROTOR,
            mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode,
            COPTER_MODE_TO_NUMBER.get(self.fc_mode, 0),
            mavutil.mavlink.MAV_STATE_ACTIVE,
        )

    def _send_rc_channels(self) -> None:
        deflected = 1900 if self.rc_override_active else 1500
        self._conn.mav.rc_channels_send(
            int(time.time() * 1000) & 0xFFFFFFFF,
            8,
            deflected, 1500, 1500, 1500,
            1500, 1500, 1500, 1500,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            255,
        )

    def _send_global_position(self) -> None:
        self._conn.mav.global_position_int_send(
            int(time.time() * 1000) & 0xFFFFFFFF,
            int(self.lat * 1e7),
            int(self.lon * 1e7),
            int(self.alt_m * 1000),
            int(self.alt_m * 1000),
            0, 0, 0, 0,
        )

    def poll_incoming(self) -> None:
        while True:
            msg = self._conn.recv_match(blocking=False)
            if msg is None:
                break
            msg_type = msg.get_type()
            if msg_type == "SET_POSITION_TARGET_LOCAL_NED":
                self.received_setpoints.append((msg.vx, msg.vy, msg.vz, msg.yaw_rate))
            elif msg_type == "COMMAND_LONG" and msg.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                # Real ArduPilot would reject an arm request with pre-arm
                # checks failing etc. - this mock always accepts it, which
                # is fine for testing that the command reaches the FC at
                # all, not for testing ArduPilot's own arming logic.
                self.armed = bool(msg.param1)
            elif msg_type == "SET_MODE":
                self.fc_mode = COPTER_NUMBER_TO_MODE.get(msg.custom_mode, self.fc_mode)

    async def run(self, rate_hz: float = 4.0) -> None:
        period = 1.0 / rate_hz
        while True:
            self._send_heartbeat()
            self._send_rc_channels()
            self._send_global_position()
            self.poll_incoming()
            await asyncio.sleep(period)
