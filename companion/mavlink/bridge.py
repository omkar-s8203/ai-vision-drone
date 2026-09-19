from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pymavlink import mavutil

# SET_POSITION_TARGET_LOCAL_NED type_mask: use velocity (vx,vy,vz) and
# yaw_rate only - ignore position, acceleration, and yaw angle.
TYPE_MASK_VELOCITY_AND_YAW_RATE = (
    (1 << 0) | (1 << 1) | (1 << 2)  # ignore position x,y,z
    | (1 << 6) | (1 << 7) | (1 << 8)  # ignore acceleration x,y,z
    | (1 << 10)  # ignore yaw angle
)

# ArduCopter custom_mode numbers for the flight modes exposed in the
# Ground Station's mode selector - a deliberate subset of all of ArduCopter's
# modes, not exhaustive (e.g. no FLIP/THROW/ZIGZAG - not relevant here).
ARDUCOPTER_MODE_TO_NUMBER: dict[str, int] = {
    "STABILIZE": 0,
    "ALT_HOLD": 2,
    "AUTO": 3,
    "GUIDED": 4,
    "LOITER": 5,
    "RTL": 6,
    "CIRCLE": 7,
    "LAND": 9,
    "POSHOLD": 16,
    "BRAKE": 17,
    "SMART_RTL": 21,
}


@dataclass
class TelemetrySnapshot:
    fc_mode: Optional[str] = None
    armed: bool = False
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_m: Optional[float] = None
    groundspeed_mps: Optional[float] = None
    battery_voltage_v: Optional[float] = None
    battery_remaining_pct: Optional[int] = None
    rc_channels: dict[int, int] = field(default_factory=dict)
    last_heartbeat_ts: Optional[float] = None
    fence_enabled: bool = False
    fence_breached: bool = False
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    satellites_visible: Optional[int] = None
    gps_fix_type: Optional[int] = None


class MavlinkBridge:
    """Standard ArduPilot companion-computer MAVLink bridge. The FC remains
    flight authority at all times - this only reads telemetry and, when
    explicitly permitted by the Safety Supervisor, writes velocity
    setpoints. See docs plan M7 and docs/safety-case.md for the RC-override
    design this bridge participates in (secondary software backstop only -
    the primary guarantee is the pilot's hardware flight-mode switch, which
    never passes through this bridge or the Pi at all).
    """

    def __init__(
        self, connection_string: str, source_system: int = 1, baud: Optional[int] = None
    ) -> None:
        self.connection_string = connection_string
        self.source_system = source_system
        self.baud = baud
        self._conn = None
        self.telemetry = TelemetrySnapshot()

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self) -> None:
        kwargs: dict = {"source_system": self.source_system}
        if self.baud is not None:
            kwargs["baud"] = self.baud
        self._conn = mavutil.mavlink_connection(self.connection_string, **kwargs)

    def prime_udp_peer(self, host: str, port: int) -> None:
        """Sim/dev-only helper: pymavlink's connected ('udpout') sockets
        can't reliably recvfrom() on Windows, so sim testing binds both ends
        via 'udpin' instead and needs one throwaway datagram sent to the
        peer so it learns our address before real traffic starts. Not
        needed on real hardware (serial link) or on Linux with 'udpout'."""
        assert self._conn is not None, "call connect() first"
        self._conn.port.sendto(b"\x00", (host, port))

    async def run(self, on_message: Optional[Callable[[object], None]] = None) -> None:
        assert self._conn is not None, "call connect() first"
        heartbeat_task = asyncio.create_task(self._own_heartbeat_loop())
        try:
            loop = asyncio.get_event_loop()
            recv = functools.partial(self._conn.recv_match, blocking=True, timeout=1.0)
            while True:
                msg = await loop.run_in_executor(None, recv)
                if msg is None:
                    continue
                self._handle_message(msg)
                if on_message:
                    on_message(msg)
        finally:
            heartbeat_task.cancel()

    async def _own_heartbeat_loop(self, rate_hz: float = 1.0) -> None:
        """Every MAVLink system, including a companion computer, is expected
        to broadcast its own heartbeat. For a UDP link this also lets the FC
        side learn the companion's address before it can send anything back
        (relevant for sim/testing over loopback UDP)."""
        period = 1.0 / rate_hz
        while True:
            self._conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0,
                mavutil.mavlink.MAV_STATE_ACTIVE,
            )
            await asyncio.sleep(period)

    def _handle_message(self, msg) -> None:
        msg_type = msg.get_type()
        if msg_type == "HEARTBEAT":
            self._conn.target_system = msg.get_srcSystem()
            self._conn.target_component = msg.get_srcComponent()
            self.telemetry.fc_mode = mavutil.mode_string_v10(msg)
            self.telemetry.armed = bool(
                msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            self.telemetry.last_heartbeat_ts = time.monotonic()
        elif msg_type == "GLOBAL_POSITION_INT":
            self.telemetry.lat = msg.lat / 1e7
            self.telemetry.lon = msg.lon / 1e7
            self.telemetry.alt_m = msg.relative_alt / 1000.0
            vx, vy = msg.vx / 100.0, msg.vy / 100.0
            self.telemetry.groundspeed_mps = (vx**2 + vy**2) ** 0.5
        elif msg_type == "GPS_RAW_INT":
            # The authoritative real-time GPS health signal - GLOBAL_POSITION_INT's
            # lat/lon can be non-null even on a stale/degraded fix, so a
            # "GPS: FIX" indicator derived from lat != null alone can lie.
            # satellites_visible is 255 when genuinely unknown (not "zero
            # satellites") - a real field bug found from a UI review: the
            # Android HUD previously hardcoded a fake "12" here because
            # nothing populated a real value.
            self.telemetry.gps_fix_type = msg.fix_type
            self.telemetry.satellites_visible = (
                msg.satellites_visible if msg.satellites_visible != 255 else None
            )
        elif msg_type == "BATTERY_STATUS":
            if msg.voltages and msg.voltages[0] != 65535:
                self.telemetry.battery_voltage_v = msg.voltages[0] / 1000.0
            self.telemetry.battery_remaining_pct = (
                msg.battery_remaining if msg.battery_remaining != -1 else None
            )
        elif msg_type == "RC_CHANNELS":
            self.telemetry.rc_channels = {
                i: getattr(msg, f"chan{i}_raw") for i in range(1, 9)
            }
        elif msg_type == "SYS_STATUS":
            # ArduPilot reports geofence status as a bit in SYS_STATUS's
            # sensor bitmasks, not a dedicated message - "enabled" means a
            # fence is actually configured (present AND enabled), "breached"
            # means it's enabled but reporting unhealthy. Bit position comes
            # from pymavlink's own MAV_SYS_STATUS_GEOFENCE constant, not a
            # hardcoded shift - this is standard MAVLink/ArduPilot behavior,
            # but (like every MAVLink integration in this project) has not
            # been confirmed against a real FC yet - see docs/safety-case.md.
            fence_bit = mavutil.mavlink.MAV_SYS_STATUS_GEOFENCE
            self.telemetry.fence_enabled = bool(msg.onboard_control_sensors_enabled & fence_bit)
            self.telemetry.fence_breached = self.telemetry.fence_enabled and not bool(
                msg.onboard_control_sensors_health & fence_bit
            )
        elif msg_type == "HOME_POSITION":
            # ArduPilot broadcasts this when home is set/changed, and
            # answers request_home_position()'s MAV_CMD_GET_HOME_POSITION
            # on request - needed for the target-recovery RTL-vs-land
            # distance estimate (companion/guidance/target_recovery.py).
            # Not yet confirmed against a real FC, like every MAVLink
            # integration in this project - see docs/safety-case.md.
            self.telemetry.home_lat = msg.latitude / 1e7
            self.telemetry.home_lon = msg.longitude / 1e7

    def arm(self, armed: bool) -> None:
        """Sends MAV_CMD_COMPONENT_ARM_DISARM - a direct, standard GCS
        command (the same thing Mission Planner/QGroundControl send), not
        gated by the Safety Supervisor. That gate exists specifically for
        autonomous guidance velocity setpoints during Follow/Approach-Test,
        not administrative FC commands - the FC's own pre-arm safety checks
        are the real guard against an unsafe arm. Never force-arms (no
        pre-arm-check bypass)."""
        assert self._conn is not None, "call connect() first"
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1 if armed else 0,
            0, 0, 0, 0, 0, 0,
        )

    def request_home_position(self) -> None:
        """Asks the FC to (re)send HOME_POSITION - ArduPilot broadcasts this
        on its own when home is set/changed, but a companion computer that
        connects after home was already set otherwise has no way to learn
        it. Call this once home is expected to exist (e.g. on the arm
        transition - see main.py) rather than polling continuously."""
        assert self._conn is not None, "call connect() first"
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_GET_HOME_POSITION,
            0,
            0, 0, 0, 0, 0, 0, 0,
        )

    def set_mode(self, mode_name: str) -> bool:
        """Sends SET_MODE for a named ArduCopter flight mode. Returns False
        (a no-op) for an unrecognized name rather than guessing."""
        mode_number = ARDUCOPTER_MODE_TO_NUMBER.get(mode_name.upper())
        if mode_number is None:
            return False
        assert self._conn is not None, "call connect() first"
        self._conn.mav.set_mode_send(
            self._conn.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_number,
        )
        return True

    def send_velocity_setpoint(
        self, vx: float, vy: float, vz: float, yaw_rate: float, guidance_allowed: bool
    ) -> bool:
        """Only ever called with a command that has already passed the
        Safety Supervisor gate; `guidance_allowed` is re-checked here too as
        a defense-in-depth backstop against a caller mistake."""
        if not guidance_allowed:
            return False
        assert self._conn is not None, "call connect() first"
        self._conn.mav.set_position_target_local_ned_send(
            int(time.monotonic() * 1000) & 0xFFFFFFFF,
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            TYPE_MASK_VELOCITY_AND_YAW_RATE,
            0, 0, 0,
            vx, vy, vz,
            0, 0, 0,
            0, yaw_rate,
        )
        return True
