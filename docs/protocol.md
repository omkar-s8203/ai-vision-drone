# Pi ↔ Android Protocol

Implemented by `companion/comms/protocol.py` (Pi) and
`android/app/.../comms/Protocol.kt` (Android) - keep both in sync when this
changes. Two separate channels, per docs plan M5/M6:

- **Control/telemetry**: WebSocket, JSON, Pi runs as the server. Every
  message is wrapped in an envelope: `{"type": str, "seq": int, "ts": float, "payload": {...}}`.
- **Video**: WebRTC, signaled over the same control channel via the
  `webrtc_offer` / `webrtc_answer` message types below, but the media itself
  is a separate peer connection - a video hiccup never blocks an abort.
  Deliberately configured with **no STUN/TURN servers on either end**
  (`AiortcVideoPipeline.handle_offer` constructs its `RTCPeerConnection`
  with the aiortc default `RTCConfiguration()`, whose `iceServers` is
  `None`; `WebRtcClient.startReceiving` passes `PeerConnection.
  RTCConfiguration(emptyList())`) - both peers are always on the same LAN
  (the Pi runs its own WiFi AP, see `companion/config/network.yaml`'s
  `mode: ap`), so host ICE candidates alone are sufficient and no external
  server is ever contacted. This is also why the whole system runs with
  **no internet access required at all** once set up: on-sensor AI
  detection (IMX500), the WebSocket control channel, MAVLink, and video are
  all local-network-only, and the Android app has no analytics/cloud SDKs.
  Internet is only needed for one-time setup (`pip install`, `git clone`,
  flashing the Pi OS/IMX500 firmware, the first Gradle build).

## Message types (`payload` shape for each)

| type | direction | payload |
|---|---|---|
| `target_select` | Android → Pi | Drag: `{x, y, w, h}` - bbox in the video's native pixel resolution, matched by IoU against current detections. Tap: `{x, y, point: true}` - matched by point-containment (whichever detection box contains the point, smallest wins on overlap) - see `select_target`/`select_target_at_point` in `companion/tracking/target_selector.py` |
| `mode_command` | Android → Pi | `{mode: "idle"\|"tracking"\|"follow"\|"orbit"\|"approach"\|"dronie"\|"parabola", follow_separation_m?: float, follow_altitude_m?: float, orbit_radius_m?: float, orbit_altitude_m?: float}` - all optional, and when present immediately override the running `FollowController`/`OrbitController`'s limits (not just at startup from `follow_limits.yaml`/`orbit_limits.yaml`). `follow_altitude_m`/`orbit_altitude_m` switch vertical control from pixel-framing to absolute altitude-hold (via `MavlinkBridge.telemetry.alt_m`). `orbit` is the DJI "circle"/point-of-interest equivalent - see `companion/guidance/orbit.py`. `dronie`/`parabola` are one-shot cinematic moves (DJI "QuickShot" equivalent) that run for a fixed `duration_s` then stop themselves - see `companion/guidance/smart_shot.py`; sending either again re-triggers a fresh run |
| `abort` | Android → Pi | `{reason: str}` |
| `arm_command` | Android → Pi | `{armed: bool}` - administrative FC command sent straight to `MavlinkBridge.arm()` (MAV_CMD_COMPONENT_ARM_DISARM), like a standard GCS - independent of the Safety Supervisor's guidance gate, which only concerns itself with velocity setpoints during active AI guidance |
| `set_flight_mode` | Android → Pi | `{mode: str}` - an ArduCopter mode name (e.g. `"LOITER"`, `"RTL"`); unknown names are a safe no-op (`MavlinkBridge.set_mode` returns `False`, nothing is sent) |
| `record_command` | Android → Pi | `{recording: bool}` - starts/stops the on-Pi local `VideoRecorder` (separate from the WebRTC feed, so footage is preserved even if the wireless link degrades) |
| `recording_state` | Pi → Android | `{recording: bool, duration_s: float}` - sent immediately after a `record_command` is handled, and then again every processed frame for as long as recording stays active so the Android timer keeps ticking (previously only sent once, at toggle time, so the on-screen duration was frozen at whatever it was at that instant even though the recording itself was genuinely running - see `CompanionOrchestrator.process_frame`). The `recording` boolean alone is also mirrored in every `health` message so a reconnecting Android client learns the current state without waiting for a toggle |
| `webrtc_offer` | Android → Pi | `{sdp: str, sdp_type: "offer"}` |
| `webrtc_answer` | Pi → Android | `{sdp: str, sdp_type: "answer"}` |
| `tracking_update` | Pi → Android | `{state, target_id, confidence, bbox: {x,y,w,h}\|null, image_width, image_height, distance_m, supervisor_state, guidance_allowed, guidance_reason}` - the one actively-tracked target, if any. `guidance_reason` is `null` when guidance is running normally, otherwise one of: `stale_subsystems:<names>`, `rc_override`, `obstacle_too_close:<class_name>:<distance>m`, `comms_lost`, `fc_not_in_ai_mode`, `target_lost` (see `companion/safety/supervisor.py`) - the Android app renders this via `GuidanceWarningBanner` |
| `detections_update` | Pi → Android | `{image_width, image_height, detections: [{bbox: {x,y,w,h}, class_name, score}, ...]}` - every object currently detected on-sensor, independent of selection/tracking, so the operator can see (and tap) anything the AI recognizes before picking a target |
| `telemetry` | Pi → Android | `{fc_mode, armed, lat, lon, alt_m, groundspeed_mps, battery_voltage_v, battery_remaining_pct, fence_enabled, fence_breached}` (mirrors `MavlinkBridge.telemetry`) - `fence_enabled`/`fence_breached` come from the FC's real `SYS_STATUS` geofence bit, so the operator can see geofence status live rather than only learning about it if an Approach-Test abort happens to reference it in `guidance_reason` |
| `health` | Pi → Android | `{pi_ok, camera_ok, ai_ok, tracker_ok, mavlink_ok, video_ok, recording, fps, latency_ms, temperature_c}` - `fps` is a real rolling average over the last 30 processed frames; `latency_ms`/`temperature_c` remain placeholders (`null`) until real pipeline timing and Pi thermal-sensor access exist (M12/hardware bring-up) |

All Pi → Android messages are sent every processed frame from
`CompanionOrchestrator.process_frame` (`companion/main.py`), piggybacking on
the camera's frame rate. Sending telemetry/health/detections at full frame
rate is wasteful bandwidth-wise for a real deployment - throttling these to
a lower fixed rate is a natural M12 (performance optimization) follow-up,
not done yet since correctness came first per the plan's priority order.
