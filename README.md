# AI Vision Drone

Companion-computer vision/AI upgrade for an existing, already-flying RC drone (RC → receiver → flight controller (ArduPilot) → ESCs → motors — unchanged). Adds a Raspberry Pi 5 + Raspberry Pi AI Camera as a vision/AI companion computer, and a native Android Ground Station app, without replacing the flight controller or taking direct motor control.

Full technical development plan (architecture, milestones, acceptance criteria, safety design): see the plan document referenced in project notes. High-level layout:

```
/companion   Python 3.11+ asyncio app running on the Pi 5 (vision, tracking, guidance, MAVLink bridge, comms, safety supervisor)
/android     Native Kotlin Ground Station app (video, target selection, telemetry, health, abort)
/sim         ArduPilot SITL harness + synthetic camera/target generator for testing before real flight
/docs        Protocol spec, safety case, hardware wiring notes
/tools       Camera calibration, IMX500 model conversion scripts
```

## Guiding priority

**STABLE → LOW LATENCY → ACCURATE → EFFICIENT → SAFE.**

The flight controller remains the sole flight authority at all times. RC override is absolute and never depends on the Pi being alive.

## Progress

**~59% - the full camera/AI/video pipeline is proven end-to-end on real hardware.** A Raspberry Pi 5 + AI Camera now run `python3 -m companion.main` in hardware mode: real on-sensor SSD MobileNetV2 detection (`class=person score=0.73`), streamed live over real WebRTC to a real Android phone, with correct colors and the full health/telemetry/tracking UI working. That process found and fixed several real bugs that had only ever been guessed at without hardware to check against - wrong picamera2 API usage, an inverted color format, a missing `pyserial` dependency, a Pi 5 Bluetooth/UART conflict (see `docs/hardware-wiring.md` for all of it). Flight-controller MAVLink wiring is in progress but not yet working; mounting on the aircraft hasn't happened yet.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Pi 5 flashed (Raspberry Pi OS Lite 64-bit), networked, SSH key access set up, camera verified, proper 5V/5A power supply confirmed necessary (a laptop USB port caused a hard freeze under video load). FC wiring in progress, drone mounting and weight/thermal checks not done yet | 35% |
| M2 | AI Camera / Detection | **Confirmed on real hardware** end-to-end through our own code, not a demo script | 85% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented, unit-tested, confirmed live from a real phone (sim + now real camera). ByteTrack swap-in still a stub | 85% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested. Rangefinder hardware addition still open (see plan) | 50% |
| M5 | Video Streaming & Pi↔Android Comms | **Confirmed live on real hardware**: real camera video, correct colors, over real WebRTC/ICE to a real phone. GStreamer hardware-encode path still stubbed (current path is the CPU-heavy software-encode "quick bringup" one, which caused one crash on inadequate power - see hardware-wiring.md) | 85% |
| M6 | Android Ground Station App | Builds, runs, every screen/control confirmed live, now including real (not just sim) video. Instrumented UI tests written but not yet run (no emulator here - see `android/README.md`) | 85% |
| M7 | MAVLink / Flight-Controller / RC Override | Bridge + RC-override monitor implemented, integration-tested against a mock FC, exercised live through Follow/Approach (sim). Real UART wiring to a Cube Orange+ in progress - not yet getting a heartbeat, mid-debugging | 65% |
| M8 | Follow-Mode | Controller implemented, unit + integration tested against mock FC, confirmed live end-to-end from the Android app including the live separation override (sim) | 70% |
| M9 | Controlled Approach-Test | Controller + every abort condition implemented, unit-tested, confirmed live from the Android app (sim) | 70% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing, abort's reset-to-idle confirmed live (sim) | 75% |
| M11 | Logging | Structured JSON logging + session recorder implemented and wired in | 70% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (73/73 tests), backed by live device tests (sim) and now live hardware tests (real camera/detection/video) | 80% |
| M14 | Real-Flight Testing Stages | Not started - blocked on FC wiring and drone mounting | 0% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`) in both sim and hardware mode, confirmed on real Pi; systemd unit file not yet written | 35% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 73 passed.

## What's next

1. **Finish wiring/debugging the flight controller UART link** (M1/M7) -
   currently mid-diagnosis: Cube Orange+ configured for MAVLink2 @ 921600 on
   a TELEM port, Pi UART enabled and correctly muxed (confirmed via
   `pinctrl`), but no heartbeat received yet and an isolated pin8/pin10
   loopback test hasn't been completed to fully isolate the remaining cause.
2. Once MAVLink is flowing, configure `FLTMODE_CH` on the transmitter for
   the RC-override design, and run hardware mode with the FC connected to
   validate the full real pipeline together (camera, tracking, MAVLink).
3. Get a heatsink/fan for the Pi 5 before further sustained video-mode
   testing - confirmed running hot/marginal under combined AI+video load.
4. Real distance calibration (`tools/calibrate_camera.py` isn't written
   yet) and the M4 rangefinder hardware decision, before Follow/Approach-Test
   get anywhere near a real flight.
5. Mounting on the aircraft, weight/power/thermal checks, then the staged
   real-flight testing sequence in the plan (M14) - props-off bench first.

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
