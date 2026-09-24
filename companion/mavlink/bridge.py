from __future__ import annotations

import asyncio
import functools
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pymavlink import mavutil

log = logging.getLogger(__name__)

# MAV_CMD_COMPONENT_ARM_DISARM's documented param2 "force" value - not a
# pymavlink-exposed named constant (checked directly: no such enum exists),
# only documented in the command's own param description text via
# pymavlink's bundled dialect ("21196: force arming/disarming (e.g. allow
# arming to override preflight checks and disarming in flight)").
FORCE_ARM_DISARM_MAGIC_NUMBER = 21196

# Position data older than this is treated as unknown by fresh_alt_m()/
# fresh_position() - guidance must not steer or apply altitude limits on it.
POSITION_MAX_AGE_S = 2.0
# Re-ask the FC for its telemetry streams if position is this stale while
# heartbeats still arrive, at most once per STREAM_RETRY_S.
STREAM_STALE_S = 3.0
STREAM_RETRY_S = 5.0

# A requested flight-mode change is confirmed by the FC's next HEARTBEAT showing the
# new mode. If it has not shown up after this long the request is re-sent (up to
# MODE_MAX_ATTEMPTS sends in total) - SET_MODE is fire-and-forget, so a request lost
# on the serial link would otherwise never be noticed.
MODE_RETRY_AFTER_S = 1.5
MODE_MAX_ATTEMPTS = 3

# Link recovery (see run()). No MAVLink data at all for this long, a read error,
# or a failed write closes the connection and reopens it - first after
# RECONNECT_MIN_DELAY_S, backing off to at most the configured max delay while
# the port cannot be opened (USB FC unplugged, still booting).
DEFAULT_SILENCE_RECONNECT_S = 5.0
DEFAULT_RECONNECT_MAX_DELAY_S = 5.0
RECONNECT_MIN_DELAY_S = 0.5

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
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    yaw_deg: Optional[float] = None
    heading_deg: Optional[float] = None
    airspeed_mps: Optional[float] = None
    climb_mps: Optional[float] = None
    throttle_pct: Optional[int] = None
    rc_rssi_pct: Optional[int] = None
    current_battery_a: Optional[float] = None
    # Monotonic time of the last GLOBAL_POSITION_INT - lat/lon/alt_m above are
    # only as trustworthy as this is recent (see MavlinkBridge.fresh_*).
    position_ts: Optional[float] = None


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
        self,
        connection_string: str,
        source_system: int = 1,
        baud: Optional[int] = None,
        silence_reconnect_s: Optional[float] = DEFAULT_SILENCE_RECONNECT_S,
        reconnect_max_delay_s: float = DEFAULT_RECONNECT_MAX_DELAY_S,
    ) -> None:
        self.connection_string = connection_string
        self.source_system = source_system
        self.baud = baud
        self.silence_reconnect_s = silence_reconnect_s  # None = never reopen on silence alone
        self.reconnect_max_delay_s = max(reconnect_max_delay_s, RECONNECT_MIN_DELAY_S)
        self._conn = None
        # Set by a failed write (see _write); run() then reopens the link.
        self._link_error: Optional[str] = None
        self._last_rx_ts: Optional[float] = None
        self.reconnect_count = 0
        self.telemetry = TelemetrySnapshot()
        # A real gap found on hardware: this bridge only ever HEARTBEATs back
        # and passively waited for the FC to stream everything else on its
        # own - HEARTBEAT is always sent regardless, but ArduPilot only
        # auto-streams GLOBAL_POSITION_INT/ATTITUDE/VFR_HUD/RC_CHANNELS/
        # SYS_STATUS/BATTERY_STATUS/GPS_RAW_INT to a link that has actually
        # asked for them (e.g. a real GCS like Mission Planner sends
        # REQUEST_DATA_STREAM on connect) - a companion computer that never
        # asks can sit there getting heartbeats forever with nothing else,
        # exactly matching a real field report: every telemetry field except
        # fc_mode/armed stayed "--" even with "Link: OK". Requested once,
        # right after the first heartbeat reveals the FC's target_system/
        # target_component (see _handle_message).
        self._requested_data_streams = False
        self._last_stream_request_ts = 0.0
        # A real, previously-documented gap ("this bridge doesn't listen
        # for COMMAND_ACK"): an arm/disarm request rejected by the FC's own
        # pre-arm checks used to be completely invisible - the operator
        # just saw nothing happen. `arm()` appends the intended new armed
        # state right before sending; _handle_message()'s COMMAND_ACK
        # handling below pops the OLDEST entry once the matching ack for
        # MAV_CMD_COMPONENT_ARM_DISARM arrives, since a bare COMMAND_ACK
        # carries no armed/disarmed intent of its own to correlate against.
        # A FIFO queue, not a single scalar: a code-review audit caught a
        # real misattribution bug in the single-value version - a rapid
        # ARM-then-DISARM double-tap (or a slow/lossy link) before the
        # first ACK arrived would overwrite the pending intent, so that
        # first ACK got attributed to the second request instead. ArduPilot
        # processes COMMAND_LONG requests over one link in order and ACKs
        # each in turn, so FIFO is the correct correlation model here, not
        # "only the most recent request matters".
        self._pending_arm_intents: list[bool] = []
        # A one-shot mailbox for main.py's process_frame() to pick up and
        # relay to the app as a real WS message, then clear - not a
        # persistent TelemetrySnapshot field, so an identical second
        # rejection in a row is never silently swallowed by simple
        # equality-based change detection the way a repeating telemetry
        # field would be.
        self.pending_arm_ack: Optional[dict] = None
        # Mode-change confirmation (see request_mode / check_pending_mode).
        self._pending_mode: Optional[dict] = None
        # One-shot mailbox like pending_arm_ack: {"mode": str, "confirmed": bool}.
        self.pending_mode_result: Optional[dict] = None

    @property
    def is_connected(self) -> bool:
        """A connection has been opened (it may be mid-reopen - writes then
        fail softly, see _write). Link health is the watchdog's "mavlink"
        heartbeat, not this."""
        return self._conn is not None

    def connect(self) -> None:
        kwargs: dict = {"source_system": self.source_system}
        if self.baud is not None:
            kwargs["baud"] = self.baud
        self._conn = mavutil.mavlink_connection(self.connection_string, **kwargs)

    def _write(self, what: str, send, *args) -> bool:
        """Every send to the FC goes through here. A write to a dead port (USB
        FC unplugged or power-cycled) raises; that used to propagate into the
        caller - skipping the whole perception frame, or silently killing the
        heartbeat task for good. Instead: report False and have run() reopen
        the link."""
        try:
            send(*args)
            return True
        except Exception as exc:
            self._mark_link_broken(f"{what} failed: {exc}")
            return False

    def _mark_link_broken(self, reason: str) -> None:
        if self._link_error is None:
            log.error("MAVLink write error - the link will be reopened (%s)", reason)
            self._link_error = reason

    def _close_quietly(self) -> None:
        conn = self._conn
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            log.debug("Closing the old MAVLink connection failed", exc_info=True)

    def position_age_s(self) -> Optional[float]:
        ts = self.telemetry.position_ts
        return None if ts is None else time.monotonic() - ts

    def fresh_alt_m(self, max_age_s: float = POSITION_MAX_AGE_S) -> Optional[float]:
        """Altitude above home, or None if it is unknown or stale. Guidance
        uses this (not telemetry.alt_m directly) so a stalled position
        stream degrades to "altitude unknown -> hold vertical" instead of
        enforcing altitude limits against a frozen number."""
        age = self.position_age_s()
        if age is None or age > max_age_s:
            return None
        return self.telemetry.alt_m

    def fresh_position(self, max_age_s: float = POSITION_MAX_AGE_S) -> Optional[tuple[float, float]]:
        age = self.position_age_s()
        if age is None or age > max_age_s:
            return None
        if self.telemetry.lat is None or self.telemetry.lon is None:
            return None
        return (self.telemetry.lat, self.telemetry.lon)

    def prime_udp_peer(self, host: str, port: int) -> None:
        """Sim/dev-only helper: pymavlink's connected ('udpout') sockets
        can't reliably recvfrom() on Windows, so sim testing binds both ends
        via 'udpin' instead and needs one throwaway datagram sent to the
        peer so it learns our address before real traffic starts. Not
        needed on real hardware (serial link) or on Linux with 'udpout'."""
        assert self._conn is not None, "call connect() first"
        self._conn.port.sendto(b"\x00", (host, port))

    async def run(self, on_message: Optional[Callable[[object], None]] = None) -> None:
        """Receives for the life of the process. A lost link used to end this
        task for good - the exception went nowhere (a background task nobody
        awaits) and telemetry stayed frozen until the service was restarted.
        Now the link is reopened (see _reconnect) and the FC's streams are
        requested again on its first heartbeat."""
        assert self._conn is not None, "call connect() first"
        heartbeat_task = asyncio.create_task(self._own_heartbeat_loop())
        try:
            while True:
                reason = await self._receive_until_link_lost(on_message)
                log.error("MAVLink link lost (%s) - reopening %s", reason, self.connection_string)
                await self._reconnect()
        finally:
            heartbeat_task.cancel()

    async def _receive_until_link_lost(self, on_message) -> str:
        """Returns why the current connection has to be reopened."""
        loop = asyncio.get_running_loop()
        recv = functools.partial(self._conn.recv_match, blocking=True, timeout=1.0)
        self._last_rx_ts = time.monotonic()
        while True:
            if self._link_error is not None:
                return self._link_error
            try:
                msg = await loop.run_in_executor(None, recv)
            except Exception as exc:
                return f"read failed: {exc}"
            now = time.monotonic()
            if msg is None:
                silent_s = now - self._last_rx_ts
                if self.silence_reconnect_s is not None and silent_s > self.silence_reconnect_s:
                    return f"no MAVLink data for {silent_s:.1f}s"
                continue
            self._last_rx_ts = now
            try:
                self._handle_message(msg)
                if on_message:
                    on_message(msg)
            except Exception:
                try:
                    msg_type = msg.get_type()
                except Exception:
                    msg_type = type(msg)
                log.exception(
                    "Failed to handle a %r MAVLink message - skipping it, receive loop stays alive",
                    msg_type,
                )

    async def _reconnect(self) -> None:
        """Close and reopen until the port opens, backing off from
        RECONNECT_MIN_DELAY_S to reconnect_max_delay_s. Never gives up: the FC
        may take a while to come back, and the Pi has nothing better to do."""
        delay = RECONNECT_MIN_DELAY_S
        while True:
            self._close_quietly()
            await asyncio.sleep(delay)
            try:
                self.connect()
            except Exception as exc:
                log.warning("Reopening MAVLink %s failed (%s) - retrying in %.1fs", self.connection_string, exc, delay)
                delay = min(delay * 2, self.reconnect_max_delay_s)
                continue
            self.reconnect_count += 1
            self._link_error = None
            # A new connection (or a rebooted FC) knows nothing of the streams
            # this link asked for - ask again on the first heartbeat.
            self._requested_data_streams = False
            log.warning("MAVLink %s reopened (reconnect #%d)", self.connection_string, self.reconnect_count)
            return

    async def _own_heartbeat_loop(self, rate_hz: float = 1.0) -> None:
        """Every MAVLink system, including a companion computer, is expected
        to broadcast its own heartbeat. For a UDP link this also lets the FC
        side learn the companion's address before it can send anything back
        (relevant for sim/testing over loopback UDP)."""
        period = 1.0 / rate_hz
        while True:
            self._write(
                "heartbeat",
                self._conn.mav.heartbeat_send,
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
            # Requested once at first contact - and again whenever position
            # data has gone stale while heartbeats keep arriving. A flight
            # controller that reboots mid-session (brown-out, watchdog) comes
            # back with its default stream rates and forgets this link ever
            # asked for anything: heartbeats resume, everything else stays
            # silent, and altitude/GPS would freeze at their last values.
            now = time.monotonic()
            position_stale = (
                self.telemetry.position_ts is None or now - self.telemetry.position_ts > STREAM_STALE_S
            )
            if not self._requested_data_streams or (
                position_stale and now - self._last_stream_request_ts > STREAM_RETRY_S
            ):
                self.request_data_streams()
                self._requested_data_streams = True
                self._last_stream_request_ts = now
        elif msg_type == "GLOBAL_POSITION_INT":
            self.telemetry.lat = msg.lat / 1e7
            self.telemetry.lon = msg.lon / 1e7
            self.telemetry.alt_m = msg.relative_alt / 1000.0
            self.telemetry.position_ts = time.monotonic()
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
            # eph/epv are HDOP/VDOP * 100 per the MAVLink spec; 65535 (UINT16_MAX)
            # is the standard "unknown" sentinel, same pattern as every other
            # unknown-value field in this bridge.
            self.telemetry.hdop = msg.eph / 100.0 if msg.eph != 65535 else None
            self.telemetry.vdop = msg.epv / 100.0 if msg.epv != 65535 else None
        elif msg_type == "BATTERY_STATUS":
            if msg.voltages and msg.voltages[0] != 65535:
                self.telemetry.battery_voltage_v = msg.voltages[0] / 1000.0
            else:
                # 65535 is the standard "unknown" sentinel (same idea as
                # GPS_RAW_INT's satellites_visible=255) - without this reset,
                # a later sensor fault left the last real voltage frozen
                # forever, silently masking the fault instead of reporting
                # "no data" like battery_remaining_pct already does below.
                self.telemetry.battery_voltage_v = None
            self.telemetry.battery_remaining_pct = (
                msg.battery_remaining if msg.battery_remaining != -1 else None
            )
            # current_battery is centiamps; -1 is the standard "not measured"
            # sentinel for this field per the MAVLink spec.
            self.telemetry.current_battery_a = (
                msg.current_battery / 100.0 if msg.current_battery != -1 else None
            )
        elif msg_type == "RC_CHANNELS":
            self.telemetry.rc_channels = {
                i: getattr(msg, f"chan{i}_raw") for i in range(1, 9)
            }
            # rssi is 0-254 (mapped to a 0-100% signal strength for display);
            # 255 is the standard "unknown" sentinel.
            self.telemetry.rc_rssi_pct = (
                round(msg.rssi * 100 / 254) if msg.rssi != 255 else None
            )
        elif msg_type == "ATTITUDE":
            self.telemetry.roll_deg = math.degrees(msg.roll)
            self.telemetry.pitch_deg = math.degrees(msg.pitch)
            self.telemetry.yaw_deg = math.degrees(msg.yaw) % 360.0
        elif msg_type == "VFR_HUD":
            self.telemetry.heading_deg = float(msg.heading)
            self.telemetry.airspeed_mps = msg.airspeed
            self.telemetry.climb_mps = msg.climb
            self.telemetry.throttle_pct = msg.throttle
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
        elif msg_type == "COMMAND_ACK":
            # A real, previously-documented gap: arm()/disarm() sent
            # MAV_CMD_COMPONENT_ARM_DISARM and never checked whether the FC
            # actually accepted it - a pre-arm-check failure (or the
            # documented "refuses disarm while it thinks it's flying" case)
            # was completely invisible, the operator just saw nothing
            # happen. COMMAND_ACK carries no armed/disarmed intent of its
            # own (just `command` and `result`), so `_pending_arm_intents`
            # (appended by arm() right before sending) is what lets this
            # message be attributed to "the arm I just asked for" vs "the
            # disarm I just asked for" - popped FIFO (oldest first), not by
            # overwriting a single scalar: a code-review audit caught that
            # a rapid ARM-then-DISARM double-tap before the first ACK
            # arrived used to misattribute that ACK to the second request
            # instead of the first.
            if (
                msg.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
                and self._pending_arm_intents
            ):
                self.pending_arm_ack = {
                    "armed_requested": self._pending_arm_intents.pop(0),
                    "accepted": msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED,
                }

    def request_data_streams(self, rate_hz: int = 4) -> None:
        """Sends a real REQUEST_DATA_STREAM(req_stream_id=MAV_DATA_STREAM_ALL)
        - the standard way a companion computer asks ArduPilot to actually
        start sending GLOBAL_POSITION_INT/ATTITUDE/VFR_HUD/RC_CHANNELS/
        SYS_STATUS/BATTERY_STATUS/GPS_RAW_INT, the same request a real GCS
        (Mission Planner/QGroundControl) sends on connect. Without this,
        ArduPilot has no reason to stream any of that to a link that never
        asked - HEARTBEAT is the one exception (sent unconditionally,
        independent of stream-rate config), which is why a real field
        report showed a healthy "Link: OK" (real HEARTBEAT parsing) with
        every other telemetry field stuck on "--" forever. Deprecated in
        favor of MAV_CMD_SET_MESSAGE_INTERVAL by the MAVLink spec, but still
        the simplest correct option here (one call covers every stream
        group ArduPilot has, individually verified via pymavlink's own
        request_data_stream_send signature and MAV_DATA_STREAM_* enum, not
        guessed) and ArduPilot still honors it."""
        assert self._conn is not None, "call connect() first"
        self._write(
            "request_data_stream",
            self._conn.mav.request_data_stream_send,
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            rate_hz,
            1,  # start_stop: 1 = start
        )

    def arm(self, armed: bool, force: bool = False) -> None:
        """Sends MAV_CMD_COMPONENT_ARM_DISARM - a direct, standard GCS
        command (the same thing Mission Planner/QGroundControl send), not
        gated by the Safety Supervisor. That gate exists specifically for
        autonomous guidance velocity setpoints during Follow/Approach-Test,
        not administrative FC commands - the FC's own pre-arm safety checks
        are the real guard against an unsafe arm. `force` is never used for
        arming (never bypasses pre-arm checks - the whole point of them).

        For disarming, ArduCopter refuses an unforced (param2=0) disarm
        outright if its own land-detector believes the aircraft is
        currently flying - real, documented MAV_CMD_COMPONENT_ARM_DISARM
        behavior (verified against pymavlink's own bundled command
        definitions, not guessed), not a bug in this bridge. That's the
        right default (a stray/errant disarm mid-flight would drop the
        aircraft), but it also means a bench test with props spinning can
        trip a false "is flying" positive and silently ignore every normal
        disarm request. `force=True` sends MAV_CMD_COMPONENT_ARM_DISARM's
        documented param2=21196 "force" value, which overrides that
        refusal - reserved for exactly that known false-positive case (or a
        genuine emergency stop), never the default path. See
        FlightControlDock.kt's separate "Force disarm" control and its own
        stronger confirmation dialog. A rejection (this one or a genuine
        pre-arm-check failure while arming) is no longer invisible - see
        this method's `_pending_arm_intents`/`pending_arm_ack` and
        _handle_message()'s COMMAND_ACK handling below, relayed to the app
        by main.py's process_frame() as a real `arm_command_result`
        message."""
        assert self._conn is not None, "call connect() first"
        # force only ever applies to disarming - `armed and force` is
        # deliberately not wired to anything, so a caller passing
        # force=True alongside armed=True can never accidentally bypass a
        # pre-arm check.
        apply_force = force and not armed
        self._pending_arm_intents.append(armed)
        sent = self._write(
            "arm/disarm",
            self._conn.mav.command_long_send,
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1 if armed else 0,
            FORCE_ARM_DISARM_MAGIC_NUMBER if apply_force else 0,
            0, 0, 0, 0, 0,
        )
        if not sent:
            # No ACK will ever come for a request that never left the Pi -
            # report it as rejected now instead of waiting on nothing.
            self._pending_arm_intents.pop()
            self.pending_arm_ack = {"armed_requested": armed, "accepted": False}

    def request_home_position(self) -> None:
        """Asks the FC to (re)send HOME_POSITION - ArduPilot broadcasts this
        on its own when home is set/changed, but a companion computer that
        connects after home was already set otherwise has no way to learn
        it. Call this once home is expected to exist (e.g. on the arm
        transition - see main.py) rather than polling continuously."""
        assert self._conn is not None, "call connect() first"
        self._write(
            "home position request",
            self._conn.mav.command_long_send,
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_GET_HOME_POSITION,
            0,
            0, 0, 0, 0, 0, 0, 0,
        )

    def takeoff(self, altitude_m: float) -> bool:
        """Sends MAV_CMD_NAV_TAKEOFF - the standard ArduCopter GUIDED-mode
        takeoff command, the same one a real GCS's "Takeoff" button sends
        (confirmed against pymavlink's own bundled command definitions -
        param7 is altitude relative to home, the rest are unused for a
        plain vertical takeoff). Once accepted, ArduCopter climbs to
        `altitude_m` autonomously using its own internal controller - this
        companion does not send (and must not send) velocity setpoints
        during that climb; it only needs to send this once and then wait,
        watching `telemetry.alt_m`, before starting to send its own
        guidance setpoints (see companion/guidance/auto_takeoff.py).
        ArduCopter rejects this command outright unless already armed and
        in GUIDED mode - real, documented behavior, not something this
        bridge needs to separately guard against. Returns False if the
        command could not be written to the link."""
        assert self._conn is not None, "call connect() first"
        return self._write(
            "takeoff",
            self._conn.mav.command_long_send,
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0, 0, 0, 0, 0, 0, altitude_m,
        )

    def set_mode(self, mode_name: str) -> bool:
        """Sends SET_MODE for a named ArduCopter flight mode. Returns False
        (a no-op) for an unrecognized name rather than guessing."""
        mode_number = ARDUCOPTER_MODE_TO_NUMBER.get(mode_name.upper())
        if mode_number is None:
            return False
        assert self._conn is not None, "call connect() first"
        self._send_mode(mode_number)
        self._pending_mode = {
            "mode": mode_name.upper(),
            "sent_ts": time.monotonic(),
            "attempts": 1,
            "mode_at_request": self.telemetry.fc_mode,
        }
        return True

    def _send_mode(self, mode_number: int) -> None:
        # A failed write is handled like a lost packet: check_pending_mode()
        # re-sends it (on the reopened link) and reports if it never took.
        self._write(
            "set_mode",
            self._conn.mav.set_mode_send,
            self._conn.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_number,
        )

    def check_pending_mode(self, allow_retry: bool = True, now: Optional[float] = None) -> None:
        """Call once per frame. Resolves the most recent set_mode() request: confirmed
        when the FC reports that mode; cancelled if someone else (the pilot's switch)
        changed the mode to something else in the meantime - never fight them; otherwise
        re-sent every MODE_RETRY_AFTER_S up to MODE_MAX_ATTEMPTS sends in total, then
        reported as not confirmed. `allow_retry=False` (pilot has RC override) waits
        without re-sending. The outcome lands in `pending_mode_result`."""
        pending = self._pending_mode
        if pending is None:
            return
        current = self.telemetry.fc_mode
        if current == pending["mode"]:
            self._pending_mode = None
            self.pending_mode_result = {"mode": pending["mode"], "confirmed": True}
            return
        if current != pending["mode_at_request"]:
            self._pending_mode = None  # the mode moved somewhere else on its own: not ours to force
            return
        now = time.monotonic() if now is None else now
        if now - pending["sent_ts"] < MODE_RETRY_AFTER_S or not allow_retry:
            return
        if pending["attempts"] >= MODE_MAX_ATTEMPTS:
            self._pending_mode = None
            self.pending_mode_result = {"mode": pending["mode"], "confirmed": False}
            log.error("FC did not switch to %s after %d requests", pending["mode"], pending["attempts"])
            return
        pending["attempts"] += 1
        pending["sent_ts"] = now
        self._send_mode(ARDUCOPTER_MODE_TO_NUMBER[pending["mode"]])

    def send_velocity_setpoint(
        self, vx: float, vy: float, vz: float, yaw_rate: float, guidance_allowed: bool
    ) -> bool:
        """Only ever called with a command that has already passed the
        Safety Supervisor gate; `guidance_allowed` is re-checked here too as
        a defense-in-depth backstop against a caller mistake."""
        if not guidance_allowed:
            return False
        assert self._conn is not None, "call connect() first"
        return self._write(
            "velocity setpoint",
            self._conn.mav.set_position_target_local_ned_send,
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
