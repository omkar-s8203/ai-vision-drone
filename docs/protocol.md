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
| `target_select` | Android → Pi | `{x, y, w, h}` - bbox in the video's native pixel resolution |
| `mode_command` | Android → Pi | `{mode: "idle"\|"tracking"\|"follow"\|"approach"}` |
| `abort` | Android → Pi | `{reason: str}` |
| `webrtc_offer` | Android → Pi | `{sdp: str, sdp_type: "offer"}` |
| `webrtc_answer` | Pi → Android | `{sdp: str, sdp_type: "answer"}` |
| `tracking_update` | Pi → Android | `{state, target_id, confidence, bbox: {x,y,w,h}\|null, image_width, image_height, distance_m, supervisor_state, guidance_allowed, guidance_reason}` |
| `telemetry` | Pi → Android | `{fc_mode, armed, lat, lon, alt_m, groundspeed_mps, battery_voltage_v, battery_remaining_pct}` (mirrors `MavlinkBridge.telemetry`) |
| `health` | Pi → Android | `{pi_ok, camera_ok, ai_ok, tracker_ok, mavlink_ok, video_ok, fps, latency_ms, temperature_c}` - `fps`/`latency_ms`/`temperature_c` are placeholders (always `null`) until M12 instrumentation exists |

All three Pi → Android messages are sent every processed frame from
`CompanionOrchestrator.process_frame` (`companion/main.py`), piggybacking on
the camera's frame rate. Sending telemetry/health at full frame rate is
wasteful bandwidth-wise for a real deployment - throttling these to a lower
fixed rate is a natural M12 (performance optimization) follow-up, not done
yet since correctness came first per the plan's priority order.
