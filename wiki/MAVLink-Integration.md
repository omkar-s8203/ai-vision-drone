# MAVLink Integration

`companion/mavlink/bridge.py` (`MavlinkBridge`) is a standard ArduPilot companion-computer bridge built on `pymavlink`. It reads telemetry and sends commands. It never overrides the FC's authority.

## Connection

| | Hardware | Sim |
|---|---|---|
| Endpoint | `/dev/serial0` (Pi UART → FC TELEM1) | `udpin:127.0.0.1:14551` ↔ mock FC on 14550 |
| Baud | **57600** (`hardware.yaml`) | - |
| Source system | 1 | 1 |

The companion sends its own `HEARTBEAT` (onboard controller) once a second.

### Asking for telemetry

ArduPilot only streams position, attitude and the rest to a link that asks. On the first FC heartbeat the bridge sends `REQUEST_DATA_STREAM(ALL, 4 Hz)`. It asks again whenever position data has gone stale (> 3 s) while heartbeats continue - at most every 5 s - which covers an FC reboot mid-session. After a reconnect it asks again on the new link.

### Reconnect

The receive task never ends. It closes and reopens the port when:

- a read raises (USB FC unplugged, port error);
- a write raised (the next receive iteration notices);
- **no MAVLink data at all for `silence_reconnect_s` (5 s)**.

Reopening retries with backoff from 0.5 s up to `reconnect_max_delay_s` (5 s), forever. While the link is down, writes return failure instead of raising: a velocity setpoint shows `guidance_sent: false`, an arm request is reported rejected, a takeoff is asked for again, and a mode request is retried like a lost packet.

## Telemetry parsed

| Message | Fields |
|---|---|
| `HEARTBEAT` | flight mode, armed; also the FC's system/component ids |
| `GLOBAL_POSITION_INT` | lat, lon, altitude above home, ground speed; timestamp for freshness |
| `GPS_RAW_INT` | fix type, satellites (255 → unknown), HDOP/VDOP (65535 → unknown) |
| `BATTERY_STATUS` | voltage (65535 → unknown), remaining % (-1 → unknown), current (-1 → unknown) |
| `RC_CHANNELS` | channels 1-8, RSSI % (255 → unknown) |
| `ATTITUDE` | roll, pitch, yaw |
| `VFR_HUD` | heading, airspeed, climb, throttle |
| `SYS_STATUS` | geofence enabled / breached (the `MAV_SYS_STATUS_GEOFENCE` bit) |
| `HOME_POSITION` | home lat/lon (requested once on arming) |
| `COMMAND_ACK` | result of arm/disarm, matched first-in-first-out to requests |

**Freshness:** guidance uses `fresh_alt_m()` and `fresh_position()`, which return nothing if the last position is older than 2 s. Unknown altitude means "no vertical motion toward the floor".

## Commands sent

| Command | MAVLink | Used for |
|---|---|---|
| Velocity setpoint | `SET_POSITION_TARGET_LOCAL_NED`, frame `BODY_OFFSET_NED`, velocity + yaw-rate mask | Guidance (only when the Supervisor allows) |
| Set mode | `SET_MODE` (custom mode) | GUIDED on mode select, LOITER on stick override, BRAKE on STOP, RTL/LAND on failsafe/recovery, the app's mode dropdown |
| Arm / disarm | `MAV_CMD_COMPONENT_ARM_DISARM`; force disarm uses param2 21196 | App Control tab |
| Takeoff | `MAV_CMD_NAV_TAKEOFF` (param7 altitude) | Arm & Follow |
| Home position | `MAV_CMD_GET_HOME_POSITION` | On arming |
| Stream request | `REQUEST_DATA_STREAM` | See above |

Supported mode names: `STABILIZE`, `ALT_HOLD`, `AUTO`, `GUIDED`, `LOITER`, `RTL`, `CIRCLE`, `LAND`, `POSHOLD`, `BRAKE`, `SMART_RTL`. Unknown names are a no-op.

Velocity axes (NED body frame): +vx forward, +vy right, **+vz down** (climb is negative vz), yaw rate in rad/s.

### Flight-mode requests are confirmed

`SET_MODE` is fire-and-forget, so every request is tracked:

- **Confirmed** when the FC's heartbeat shows the new mode.
- Not seen after 1.5 s → re-sent, up to **3 sends** in total, then reported `confirmed: false` (the app says "Flight controller did not change mode").
- If the mode changes to something **else** meanwhile (the pilot's switch), the request is dropped - the Pi never fights the pilot.
- No re-sends while the pilot has stick override.

The outcome goes to the app as `mode_change_result` and to the session log.

### Arm and disarm feedback

Every arm or disarm gets a `COMMAND_ACK`. It is matched to the request (a queue, so a quick arm-then-disarm is attributed correctly) and sent to the app as `arm_command_result`. A rejection is spoken ("Arm rejected by flight controller").

ArduCopter refuses a normal disarm if its land detector thinks it is flying - a bench test with props spinning can trip this. **Force disarm** overrides it, is never applied to arming, and is refused above 1.5 m.

## RC override detection

`companion/mavlink/rc_monitor.py` watches channels **1-4 (roll, pitch, throttle, yaw)**. A channel counts as override when it is more than `rc_override_deadband` (0.15, from `approach_limits.yaml`) of half-travel away from 1500 µs - that is, outside **1425-1575 µs** with the default 500 µs half-range.

> Throttle (channel 3) is included, so **the throttle stick must rest near centre** (as it does for LOITER/ALT_HOLD flying) while the Pi guides. A throttle held low reads as permanent override and guidance will never be allowed. Check this during the Stage 4 bench test.

This is a secondary backstop. The primary guarantee is the hardware switch; see [Safety Architecture](Safety-Architecture#rc-override).

## Verified against

The real Cube Orange: heartbeat, telemetry streams, arm/disarm, reading and setting modes. The mock FC and unit tests only: guidance setpoints, geofence bit, `HOME_POSITION`, takeoff, BRAKE/RTL/LAND behaviour, reconnect. **No velocity setpoint has reached the real FC yet.**
