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

**~58% - real hardware bring-up has started, and the camera/AI path is proven end-to-end.** A Raspberry Pi 5 + AI Camera are now flashed, networked, and running our actual `Picamera2IMX500Camera`/`IMX500Detector` code against a real on-sensor SSD MobileNetV2 detector - not simulated, a real person in frame produced `class=person score=0.73`, with plausible tracking boxes across frames. That process also found and fixed real bugs in code that had only ever been guessed at without hardware to check against (see `docs/hardware-wiring.md`). Flight-controller wiring/MAVLink and mounting on the aircraft haven't happened yet.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Pi 5 flashed (Raspberry Pi OS Lite 64-bit), networked, SSH key access set up, camera physically connected and verified. FC wiring, drone mounting, and weight/thermal checks not done yet | 30% |
| M2 | AI Camera / Detection | **Confirmed on real hardware**: `imx500-all` + `python3-picamera2` installed, on-sensor SSD MobileNetV2 detection verified live, and `Picamera2IMX500Camera`/`IMX500Detector` fixed to match the real API (see `docs/hardware-wiring.md`) | 85% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented, unit-tested, and confirmed live from a real phone (against sim). ByteTrack swap-in still a stub | 85% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested. Rangefinder hardware addition still open (see plan) | 50% |
| M5 | Video Streaming & Pi↔Android Comms | WebSocket control/telemetry/WebRTC-signaling channel confirmed live end-to-end against a real phone across every mode (sim). GStreamer hardware-encode path still stubbed | 75% |
| M6 | Android Ground Station App | Builds, runs, and every screen/control confirmed live against the sim stack: video, drag-to-select, tracking overlay, telemetry/health, mode controls incl. live follow-separation, WS reconnect, abort. Instrumented UI tests written but not yet run (no emulator here - see `android/README.md`) | 85% |
| M7 | MAVLink / Flight-Controller / RC Override | Bridge + RC-override monitor implemented, integration-tested against a mock FC, exercised live through Follow/Approach (sim). Real serial connection to an actual flight controller not yet tried | 65% |
| M8 | Follow-Mode | Controller implemented, unit + integration tested against mock FC, confirmed live end-to-end from the Android app including the live separation override (sim) | 70% |
| M9 | Controlled Approach-Test | Controller + every abort condition implemented, unit-tested, confirmed live from the Android app (sim) | 70% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing, abort's reset-to-idle confirmed live (sim) | 75% |
| M11 | Logging | Structured JSON logging + session recorder implemented and wired in | 70% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (73/73 tests), backed by live device tests (sim) and now a live hardware test (real camera/detection) | 78% |
| M14 | Real-Flight Testing Stages | Not started - blocked on FC wiring and drone mounting | 0% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`), now with video included; systemd unit file not yet written | 30% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 73 passed.

## What's next

1. **Wire the flight controller to the Pi** (M1/M7) - UART connection to the
   FC's telemetry port, confirm MAVLink heartbeats flow both ways, then
   configure `FLTMODE_CH` on the transmitter for the RC-override design.
2. Run `python3 -m companion.main` in hardware mode on the Pi itself once
   MAVLink is wired, to validate the full real pipeline (not just the
   detector in isolation) - camera, tracking, and MAVLink bridge together.
3. Real distance calibration (`tools/calibrate_camera.py` isn't written
   yet) and the M4 rangefinder hardware decision, before Follow/Approach-Test
   get anywhere near a real flight.
4. Mounting on the aircraft, weight/power/thermal checks, then the staged
   real-flight testing sequence in the plan (M14) - props-off bench first.

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
