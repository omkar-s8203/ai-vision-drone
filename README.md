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

**~53% toward a fully-simulated, hardware-ready system.** Build order has been: full companion (Pi-side) code first, using mock/synthetic implementations for anything hardware-dependent, then a simulation harness, then integration, then the Android app. Real hardware bring-up (M1, M14) hasn't started - but **every software mode is now live-validated**: a real Android phone, over real WiFi, connected to the sim companion stack - target selection, Tracking, Follow (including the live separation slider), Approach-Test, and abort have all been confirmed working, not just unit-tested against mocks.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Not started - blocked on physical hardware | 0% |
| M2 | AI Camera / Detection | Interfaces + sim path done (`SyntheticCamera`, `IMX500Detector`); untestable until real camera | 40% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented, unit-tested, **and confirmed live** from a real phone. ByteTrack swap-in still a stub | 85% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested. Rangefinder hardware addition still open (see plan) | 50% |
| M5 | Video Streaming & Pi↔Android Comms | WebSocket control/telemetry/WebRTC-signaling channel **confirmed live end-to-end** against a real phone across every mode. GStreamer hardware-encode path still stubbed | 75% |
| M6 | Android Ground Station App | Builds, runs, and every screen/control confirmed live against the sim stack: video, drag-to-select, tracking overlay, telemetry/health, mode controls incl. live follow-separation, WS reconnect, abort. Instrumented UI tests written but not yet run (no emulator here - see `android/README.md`) | 85% |
| M7 | MAVLink / Flight-Controller / RC Override | Bridge + RC-override monitor implemented, integration-tested against a mock FC, and now exercised live through Follow/Approach running against the sim's mock flight controller | 65% |
| M8 | Follow-Mode | Controller implemented, unit + integration tested against mock FC, **and confirmed live** end-to-end from the Android app including the live separation override | 70% |
| M9 | Controlled Approach-Test | Controller + every abort condition (target-loss, comms-loss, RC-override, geofence, no-distance) implemented, unit-tested, **and confirmed live** from the Android app | 70% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing, abort's reset-to-idle confirmed live | 75% |
| M11 | Logging | Structured JSON logging + session recorder implemented and wired in | 70% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (68/68 tests), now backed by live device tests across every mode | 75% |
| M14 | Real-Flight Testing Stages | Not started - blocked on physical hardware | 0% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`), now with video included; systemd unit file not yet written | 30% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 68 passed.

## What's next

Everything meaningfully buildable and testable in software is now done and
live-validated. What's left genuinely needs the physical Pi 5 + AI Camera +
flight controller:
1. **Hardware bring-up (M1)** once the parts are in hand - Pi power, UART
   wiring to the flight controller, camera mount, weight/thermal checks.
2. **Swap sim components for real ones**: `Picamera2IMX500Camera` and
   `IMX500Detector` (M2) instead of the synthetic path, a real serial
   MAVLink connection (M7) instead of the mock flight controller, real
   `FLTMODE_CH` RC-override configuration on the actual transmitter/FC.
3. Smaller, not-blocking polish: run the instrumented Android tests on a
   real device/emulator, throttle telemetry/health send rate (currently
   every frame - fine for now, wasteful long-term per M12), real distance
   calibration (`tools/calibrate_camera.py` isn't written yet).

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
