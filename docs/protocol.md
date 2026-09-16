# Pi ↔ Android Protocol

Implemented by `companion/comms/protocol.py` (Pi) and
`android/app/.../comms/Protocol.kt` (Android) - keep both in sync when this
changes. Two separate channels, per docs plan M5/M6:

- **Control/telemetry**: WebSocket, JSON, Pi runs as the server. Every
  message is wrapped in an envelope: `{"type": str, "seq": int, "ts": float, "payload": {...}}`.
- **Video**: WebRTC, signaled over the same control channel via the
  `webrtc_offer` / `webrtc_answer` message types below, but the media itself
  is a separate peer connection - a video hiccup never blocks an abort.

## Message types (`payload` shape for each)

| type | direction | payload |
|---|---|---|
| `target_select` | Android → Pi | Drag: `{x, y, w, h}` - bbox in the video's native pixel resolution, matched by IoU against current detections. Tap: `{x, y, point: true}` - matched by point-containment (whichever detection box contains the point, smallest wins on overlap) - see `select_target`/`select_target_at_point` in `companion/tracking/target_selector.py` |
| `mode_command` | Android → Pi | `{mode: "idle"\|"tracking"\|"follow"\|"approach", follow_separation_m?: float, follow_altitude_m?: float}` - both optional, and when present immediately override the running `FollowController`'s limits (not just at startup from `follow_limits.yaml`). `follow_altitude_m` switches vertical control from pixel-framing to absolute altitude-hold (via `MavlinkBridge.telemetry.alt_m`) |
| `abort` | Android → Pi | `{reason: str}` |
| `webrtc_offer` | Android → Pi | `{sdp: str, sdp_type: "offer"}` |
| `webrtc_answer` | Pi → Android | `{sdp: str, sdp_type: "answer"}` |
| `tracking_update` | Pi → Android | `{state, target_id, confidence, bbox: {x,y,w,h}\|null, image_width, image_height, distance_m, supervisor_state, guidance_allowed, guidance_reason}` - the one actively-tracked target, if any |
| `detections_update` | Pi → Android | `{image_width, image_height, detections: [{bbox: {x,y,w,h}, class_name, score}, ...]}` - every object currently detected on-sensor, independent of selection/tracking, so the operator can see (and tap) anything the AI recognizes before picking a target |
| `telemetry` | Pi → Android | `{fc_mode, armed, lat, lon, alt_m, groundspeed_mps, battery_voltage_v, battery_remaining_pct}` (mirrors `MavlinkBridge.telemetry`) |
| `health` | Pi → Android | `{pi_ok, camera_ok, ai_ok, tracker_ok, mavlink_ok, video_ok, fps, latency_ms, temperature_c}` - `fps` is a real rolling average over the last 30 processed frames; `latency_ms`/`temperature_c` remain placeholders (`null`) until real pipeline timing and Pi thermal-sensor access exist (M12/hardware bring-up) |

All Pi → Android messages are sent every processed frame from
`CompanionOrchestrator.process_frame` (`companion/main.py`), piggybacking on
the camera's frame rate. Sending telemetry/health/detections at full frame
rate is wasteful bandwidth-wise for a real deployment - throttling these to
a lower fixed rate is a natural M12 (performance optimization) follow-up,
not done yet since correctness came first per the plan's priority order.
