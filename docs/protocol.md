# Pi ↔ Android Protocol

Status: not yet written — this will be filled in during M5 (Video Streaming & Pi↔Android Communication).

Planned shape:
- Control/telemetry channel: WebSocket, JSON messages, versioned envelope `{type, seq, ts, payload}`.
- Video channel: WebRTC (separate from the control channel so video issues never block a STOP command).

Message types to define here once implemented: target selection, mode commands (Normal/Tracking/Follow/Approach-Test), abort/stop, tracking status updates, telemetry snapshots, system health snapshots.
