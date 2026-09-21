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
        self.fence_enabled = False
        self.fence_breached = False
        self.home_lat = 0.0
        self.home_lon = 0.0
        self.home_set = False
        self.gps_fix_type = 3  # 3D fix by default - matches MAV_GPS_FIX_TYPE
        self.satellites_visible = 12
        self.battery_voltage_mv = 12400  # a healthy-looking pack voltage
        self.battery_remaining_pct = 80
        self.current_battery_ca = 1500  # centiamps -> 15.0A, a plausible hover draw
        self.hdop_x100 = 120  # -> 1.20 HDOP, a decent fix
        self.vdop_x100 = 180
        self.rc_rssi = 200  # 0-254 scale
        self.roll_rad = 0.0
        self.pitch_rad = 0.0
        self.yaw_rad = 0.0
        self.heading_deg = 0
        self.airspeed_mps = 0.0
        self.climb_mps = 0.0
        self.throttle_pct = 0
        self.received_setpoints: list[tuple[float, float, float, float]] = []
        self.received_data_stream_requests: list[tuple[int, int, int]] = []

    def set_mode(self, mode: str) -> None:
        """Simulates the pilot's hardware mode switch changing the FC mode -
        in reality this never touches the Pi at all; here it just flips the
        mock's reported mode so the bridge/supervisor reaction can be tested."""
        self.fc_mode = mode

    def set_armed(self, armed: bool) -> None:
        self.armed = armed

    def set_rc_override(self, active: bool) -> None:
        self.rc_override_active = active

    def set_home(self, lat: float, lon: float) -> None:
        """Real ArduPilot sets home at arm time (or wherever GPS first gets
        a fix) - this test double requires it to be set explicitly rather
        than defaulting to "always available", so a test can also exercise
        the real "home not set yet" case (request_home_position() answered
        with nothing, matching a real FC before GPS fix)."""
        self.home_lat = lat
        self.home_lon = lon
        self.home_set = True

    def set_gps(self, fix_type: int, satellites_visible: int) -> None:
        self.gps_fix_type = fix_type
        self.satellites_visible = satellites_visible

    def set_battery(self, voltage_mv: int, remaining_pct: int) -> None:
        """Pass voltage_mv=65535 or remaining_pct=-1 to simulate the
        standard MAVLink "unknown" sentinel for that one field."""
        self.battery_voltage_mv = voltage_mv
        self.battery_remaining_pct = remaining_pct

    def set_attitude(self, roll_rad: float, pitch_rad: float, yaw_rad: float) -> None:
        self.roll_rad = roll_rad
        self.pitch_rad = pitch_rad
        self.yaw_rad = yaw_rad

    def set_vfr_hud(
        self, heading_deg: int, airspeed_mps: float, climb_mps: float, throttle_pct: int
    ) -> None:
        self.heading_deg = heading_deg
        self.airspeed_mps = airspeed_mps
        self.climb_mps = climb_mps
        self.throttle_pct = throttle_pct

    def set_rc_rssi(self, rssi: int) -> None:
        """Pass 255 to simulate the standard "unknown" sentinel."""
        self.rc_rssi = rssi

    def set_gps_dilution(self, hdop_x100: int, vdop_x100: int) -> None:
        """Pass 65535 to simulate the standard "unknown" sentinel."""
        self.hdop_x100 = hdop_x100
        self.vdop_x100 = vdop_x100

    def set_current_battery(self, current_ca: int) -> None:
        """Pass -1 to simulate the standard "not measured" sentinel."""
        self.current_battery_ca = current_ca

    def set_fence_state(self, enabled: bool, breached: bool = False) -> None:
        """`breached` only means anything when `enabled` is True - matches
        real ArduPilot semantics (SYS_STATUS's health bit for a sensor that
        isn't even enabled is meaningless)."""
        self.fence_enabled = enabled
        self.fence_breached = enabled and breached

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
            self.rc_rssi,
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

    def _send_gps_raw_int(self) -> None:
        self._conn.mav.gps_raw_int_send(
            int(time.time() * 1e6) & 0xFFFFFFFFFFFFFFFF,
            self.gps_fix_type,
            int(self.lat * 1e7), int(self.lon * 1e7), int(self.alt_m * 1000),
            self.hdop_x100, self.vdop_x100, 0, 0,
            self.satellites_visible,
        )

    def _send_battery_status(self) -> None:
        voltages = [self.battery_voltage_mv] + [65535] * 9  # only cell/pack slot 0 is used here
        self._conn.mav.battery_status_send(
            0, 0, 0, 32767,  # id, battery_function, type, temperature (32767 = unknown)
            voltages,
            self.current_battery_ca, -1, -1,  # current_consumed, energy_consumed - not measured
            self.battery_remaining_pct,
        )

    def _send_attitude(self) -> None:
        self._conn.mav.attitude_send(
            int(time.time() * 1000) & 0xFFFFFFFF,
            self.roll_rad, self.pitch_rad, self.yaw_rad,
            0.0, 0.0, 0.0,
        )

    def _send_vfr_hud(self) -> None:
        self._conn.mav.vfr_hud_send(
            self.airspeed_mps, 0.0, self.heading_deg, self.throttle_pct,
            self.alt_m, self.climb_mps,
        )

    def _send_sys_status(self) -> None:
        fence_bit = mavutil.mavlink.MAV_SYS_STATUS_GEOFENCE if self.fence_enabled else 0
        # "Healthy" means NOT breached, so the health bit is only cleared
        # while enabled AND breached - matches how MavlinkBridge interprets
        # it (see companion/mavlink/bridge.py's SYS_STATUS handling).
        health_bit = fence_bit if not self.fence_breached else 0
        self._conn.mav.sys_status_send(
            fence_bit, fence_bit, health_bit,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        )

    def _send_home_position(self) -> None:
        """Answers a real MAV_CMD_GET_HOME_POSITION request
        (companion/mavlink/bridge.py's request_home_position()) with a real
        HOME_POSITION message - confirmed field order/types against
        pymavlink directly (home_position_send's real signature), not
        guessed."""
        self._conn.mav.home_position_send(
            int(self.home_lat * 1e7), int(self.home_lon * 1e7), 0,
            0.0, 0.0, 0.0,
            [1.0, 0.0, 0.0, 0.0],
            0.0, 0.0, 0.0,
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
            elif msg_type == "COMMAND_LONG" and msg.command == mavutil.mavlink.MAV_CMD_GET_HOME_POSITION:
                if self.home_set:
                    self._send_home_position()
                # Real ArduPilot would also NACK via COMMAND_ACK if home
                # isn't set yet - not modeled here since nothing in this
                # project reads COMMAND_ACK for this request today.
            elif msg_type == "SET_MODE":
                self.fc_mode = COPTER_NUMBER_TO_MODE.get(msg.custom_mode, self.fc_mode)
            elif msg_type == "REQUEST_DATA_STREAM":
                self.received_data_stream_requests.append(
                    (msg.req_stream_id, msg.req_message_rate, msg.start_stop)
                )

    async def run(self, rate_hz: float = 4.0) -> None:
        period = 1.0 / rate_hz
        while True:
            self._send_heartbeat()
            self._send_rc_channels()
            self._send_global_position()
            self._send_gps_raw_int()
            self._send_battery_status()
            self._send_sys_status()
            self._send_attitude()
            self._send_vfr_hud()
            self.poll_incoming()
            await asyncio.sleep(period)
