# Communication Protocol

The authoritative spec is `docs/protocol.md`; the Pi side is `companion/comms/protocol.py` and the app side is `android/.../comms/Protocol.kt` - keep both in sync.

## Channels

| Channel | Transport | Purpose |
|---|---|---|
| Control / telemetry | WebSocket, JSON, Pi is the server on port **8765** | Commands, telemetry, tracking, health, events |
| Video | WebRTC (signalled over the WebSocket) | Camera image, separate so a video stall never blocks STOP |

Both are LAN-only. WebRTC uses no STUN/TURN servers - the phone and Pi share the Pi's own access point, so host candidates are enough.

## Envelope

Every WebSocket message:

```json
{"type": "tracking_update", "seq": 1234, "ts": 1695550000.123, "payload": { ... }}
```

A malformed message is dropped and logged; it never closes the connection.

## Liveness and flow control

- The app **must** send `ping` every 500 ms. The Pi answers with `pong` echoing the payload. No message of any kind for 3 s → the Pi declares the operator link lost.
- Each app connection has its own bounded send queue on the Pi (200 messages, about a second). A client that falls that far behind is closed with code **1013** ("try again later") and should reconnect.
- All Pi → app streaming messages are sent once per processed camera frame.

## App → Pi

| Type | Payload | Effect |
|---|---|---|
| `target_select` | tap `{x, y, point: true}` or drag `{x, y, w, h}` (video pixels) | Pick a target |
| `mode_command` | `{mode, follow_separation_m?, follow_altitude_m?, orbit_radius_m?, orbit_altitude_m?, follow_max_speed_mps?, orbit_max_speed_mps?, grid_search_width_m?, grid_search_height_m?, grid_search_heading_deg?, auto_takeoff?}` | Change mode and/or live parameters (clamped). `mode` ∈ `idle`, `tracking`, `follow`, `orbit`, `approach`, `grid_search` |
| `abort` | `{reason}` | STOP |
| `arm_command` | `{armed, force?}` | Arm / disarm (`force` only for disarm) |
| `set_flight_mode` | `{mode}` | Set an ArduCopter mode by name |
| `record_command` | `{recording}` | Start/stop Pi-side recording |
| `teach_object` | `{x, y, w, h, name, real_width_m?, real_height_m?}` | Start Teach mode |
| `land_confirmation_response` | `{approved}` | Answer to a landing request |
| `webrtc_offer` | `{sdp, sdp_type: "offer"}` | Start video |
| `ping` | any | Keep-alive and latency probe |

## Pi → App

| Type | Payload (main fields) | When |
|---|---|---|
| `tracking_update` | `state`, `target_id`, `confidence`, `bbox`, `image_width/height`, `distance_m`, `supervisor_state`, `guidance_allowed`, `guidance_reason`, `commanded_vx/vy/vz_mps`, `commanded_yaw_rate_rads`, `guidance_sent`, `guidance_hold`, `teaching`, `teach_samples` | Every frame |
| `detections_update` | `image_width/height`, `detections: [{bbox, class_name, score}]` (last real result repeated for ≤ 0.5 s on frames without one) | Every frame |
| `grid_search_update` | `active`, `phase`, `waypoints: [[lat, lon]]`, `current_index` | Every frame |
| `telemetry` | flight mode, armed, lat/lon/alt, ground speed, battery V/%/A, fence enabled/breached, satellites, fix type, HDOP/VDOP, home, distance/bearing to home, roll/pitch/yaw, heading, airspeed, climb, throttle, RC RSSI | Every frame |
| `health` | `pi_ok`, `camera_ok`, `ai_ok`, `tracker_ok`, `mavlink_ok`, `video_ok`, `recording`, `fps` (`latency_ms`, `temperature_c` still null) | Every frame |
| `recording_state` | `recording`, `duration_s` | On toggle, then every frame while recording |
| `arm_command_result` | `armed_requested`, `accepted` | Once per FC acknowledgement |
| `mode_change_result` | `mode`, `confirmed` | Once per flight-mode request outcome |
| `teach_result` | `ok`, `name?`, `has_distance?`, `reason?` | Once per `teach_object` |
| `land_confirmation_request` | `distance_to_home_m`, `battery_remaining_pct`, `obstacle_detected`, `obstacle_class_name` | Once, when recovery wants to land |
| `webrtc_answer` | `sdp`, `sdp_type: "answer"` | Reply to an offer |
| `pong` | the `ping` payload | Reply to a ping |

### `guidance_reason` values

`null` when running, else `stale_subsystems:<names>`, `rc_override`, `geofence_breached`, `battery_critical`, `obstacle_too_close:<class>:<m>m`, `comms_lost`, `fc_not_in_ai_mode`, `target_lost`.

### `guidance_hold` values

`null`, `auto_takeoff`, `target_unseen`, `identity_lost`, `gps_degraded`, `takeoff_refused_gps`, `takeoff_refused_battery`.

### Tracking `state` values

`IDLE`, `TRACKING`, `REACQUIRE`, `TARGET_LOST`.

### `supervisor_state` values

`IDLE`, `TRACKING`, `FOLLOWING`, `ORBITING`, `APPROACHING`, `SEARCHING`, `GRID_SEARCH`, `SAFE`.

## Watching the stream

`tools/live_monitor.py` prints everything the Pi sends, one readable line per message, without sending anything itself. See [Tools](Tools#live_monitorpy).

## Known follow-ups

- Streaming messages go out at full camera rate; throttling telemetry/health to a lower rate is a planned performance item.
- `docs/protocol.md` has an outdated line saying the production app does not send `ping` - it does, every 500 ms.
