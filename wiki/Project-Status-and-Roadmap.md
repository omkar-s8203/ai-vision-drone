# Project Status and Roadmap

**Overall: ~72 %.** All software is implemented and tested (763 companion tests passing; the Android app builds and runs on a real phone). The full stack runs together on the real Pi and Cube Orange, mounted on the aircraft, props off. Real flight has not started.

## Confirmed on real hardware

- On-sensor detection at 27.1 FPS, 0.3 ms latency, ~12 % CPU; live boxes in the app.
- Real video over WebRTC to a real phone, correct colours, ~30 FPS.
- MAVLink over TELEM1 at 57600: heartbeat, full telemetry (position, attitude, GPS, battery, RSSI), arm/disarm, reading and setting flight modes.
- The app end to end: connect, video, tap/drag selection, tracking overlay, arm/disarm, mode dropdown, guidance buttons, obstacle banner, recording timer, phone-side recording.
- One distance data point: a person at 2 m read 1.9-2.0 m.

## Not yet done (all need hands on hardware)

| Priority | Item | Next action |
|---|---|---|
| 🔴 | `FLTMODE_CH` not configured on the transmitter | Configure, then verify with the Pi off and 20/20 during guidance (lab Stage 4) |
| 🔴 | No guidance setpoint has reached the real FC | Props-off guidance dry run (lab Stage 7) |
| 🟡 | Geofence signal unconfirmed against real ArduPilot | Enable `FENCE_ENABLE` on the bench, confirm the breach flag flips |
| 🟡 | Camera never calibrated (placeholder intrinsics) | `tools/calibrate_camera.py` with a printed board; then distance validation |
| 🟡 | Target-loss recovery untested on hardware | Alongside the guidance dry run |
| 🟡 | This safety pass (flicker carry-over, MAVLink reconnect, service watchdog, slow client, camera stall) untested on the Pi | Lab rows 5.10, 6A.5, 7C.3, 7C.5-7C.6, 9.12, 10.7-10.8 |
| ⚪ | Flight power, weight/CG, thermal soak | Buck converter off the flight battery; soak test |
| ⚪ | Real flight stages 1-5 | Only after the lab go/no-go |

## Milestones

| # | Milestone | % | Where it stands |
|---|---|---|---|
| M1 | Hardware integration | 68 | Pi, camera and FC wired and mounted; flight power and weight/thermal checks open |
| M2 | AI camera / detection | 97 | Benchmarked and passing on the Pi; threshold tuned from real data; Teach mode added |
| M3 | Tracking, selection, reacquisition | 91 | Live on hardware; identity check and motion model added; reacquisition metrics not yet measured on real data; ByteTrack optional |
| M4 | Distance estimation | 70 | Height-based, clipping-aware, filtered; calibration and ground-truth validation outstanding; rangefinder driver ready, sensor not bought |
| M5 | Video and Pi↔app comms | 89 | Live on hardware; recording made non-blocking; slow-client isolation added; real WS and glass-to-glass latency not yet measured; GStreamer pipeline unverified |
| M6 | Android app | 94 | Five-tab app live on a phone; newer overlays and alerts build-verified only |
| M7 | MAVLink / FC / RC override | 87 | Telemetry and admin commands live; ACK handling, mode confirmation, reconnect; `FLTMODE_CH` and guidance setpoints outstanding |
| M8 | Follow / Orbit and other modes | 83 | Follow, Orbit, Grid Search, recovery, Arm & Follow implemented and tested against the mock FC; limits enforced |
| M9 | Approach-Test | 76 | All abort conditions tested; fence unconfirmed on a real FC |
| M10 | Safety architecture and watchdog | 91 | Supervisor, failsafes, safety case; process-level watchdog now active |
| M11 | Logging | 78 | JSON logs, session recorder with pruning |
| M12 | Performance optimisation | 0 | Deliberately deferred until correctness is proven (e.g. throttle telemetry, hardware video encode) |
| M13 | Testing and simulation | 91 | 763 tests, mock FC, real-WebSocket end-to-end test, SITL launcher |
| M14 | Real-flight stages | 15 | Stage 1 (bench, props off, mounted) reached |
| M15 | Deployment and monitoring | 62+ | systemd service with watchdog and restart; boot health check; power-cycle test on the Pi outstanding |
| M16 | Future scalability | n/a | Design notes only |

## Deliberately removed

The Dronie and Parabola smart-shot modes were built and then removed entirely at the owner's request. Follow, Orbit, Approach and Grid Search are unaffected.

## Future ideas (not scheduled)

- Throttle telemetry and health to a fixed lower rate (M12).
- Hardware H.264 encoding via GStreamer (a draft exists, never run).
- Real Pi temperature and pipeline latency in the health message.
- Handle server-initiated close (`onClosing`) in the app's WebSocket client for instant reconnects.
- A long-range radio link behind the existing `Transport` interface.
- Retrained models with taught objects plus the everyday classes.

## Recent safety pass (September 2026)

- Frames without an AI result no longer cause flicker or stutter (reuse the last result for up to 0.5 s; hold only after 0.3 s unseen).
- The MAVLink link reopens by itself after errors or 5 s of silence.
- The service is now `Type=notify` with a 10 s watchdog and always restarts; the watchdog had never worked before (missing dependency).
- A slow phone can no longer stall the control loop.
- A hung camera is detected in 2 s and the service restarts.
- All the new thresholds are config parameters, range-checked at boot.
- Follow-up fixes: taps wait for a fresh AI result; the reacquire timer counts from the last sighting; failed writes are no longer logged as sent; a takeoff lost on a dropped link is re-sent.
