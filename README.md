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

**~61% - camera, AI, video, and MAVLink are all confirmed working end-to-end on real hardware.** A Raspberry Pi 5 + AI Camera + Cube Orange flight controller are now all wired together and talking: real on-sensor SSD MobileNetV2 detection, real video streamed over WebRTC to a real Android phone, and real MAVLink (heartbeat + 10Hz ATTITUDE) over TELEM1. Getting MAVLink working took a long debugging session whose actual root cause was a baud-rate mismatch (57600, not 921600 - the FC never actually adopted the GCS-configured baud despite the UI showing it applied) - see `docs/hardware-wiring.md` for the full story and every other real bug this hardware phase surfaced. Mounting on the aircraft and RC-override transmitter configuration haven't happened yet.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Pi 5 + AI Camera + flight controller all wired and confirmed working together on a bench. Drone mounting, flight-battery power source, and weight/thermal checks not done yet | 50% |
| M2 | AI Camera / Detection | **Confirmed on real hardware** end-to-end through our own code, not a demo script | 85% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented, unit-tested, confirmed live from a real phone (sim + now real camera). ByteTrack swap-in still a stub | 85% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested. Rangefinder hardware addition still open (see plan) | 50% |
| M5 | Video Streaming & Pi↔Android Comms | **Confirmed live on real hardware**: real camera video, correct colors, over real WebRTC/ICE to a real phone. GStreamer hardware-encode path still stubbed (current path is the CPU-heavy software-encode "quick bringup" one, which caused one crash on inadequate power - see hardware-wiring.md) | 85% |
| M6 | Android Ground Station App | Builds, runs, every screen/control confirmed live, now including real (not just sim) video. Instrumented UI tests written but not yet run (no emulator here - see `android/README.md`) | 85% |
| M7 | MAVLink / Flight-Controller / RC Override | **Real MAVLink link confirmed working**: heartbeat + 10Hz ATTITUDE over TELEM1 @ 57600 baud with a real Cube Orange. `FLTMODE_CH` RC-override switch not yet configured on the transmitter - that's the one piece of this milestone still open | 80% |
| M8 | Follow-Mode | Controller implemented, unit + integration tested against mock FC, confirmed live end-to-end from the Android app including the live separation override (sim) | 70% |
| M9 | Controlled Approach-Test | Controller + every abort condition implemented, unit-tested, confirmed live from the Android app (sim) | 70% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing, abort's reset-to-idle confirmed live (sim) | 75% |
| M11 | Logging | Structured JSON logging + session recorder implemented and wired in | 70% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (75/75 tests), backed by live device tests (sim) and now live hardware tests (real camera/detection/video/MAVLink) | 82% |
| M14 | Real-Flight Testing Stages | Not started - blocked on drone mounting | 0% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`) in both sim and hardware mode, confirmed on real Pi; systemd unit file not yet written | 35% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 75 passed.

## What's next

1. **Run `companion.main` in hardware mode with the FC actually connected** -
   so far we've only proven the camera/video path and the MAVLink link
   separately; running them together is the next real integration test
   (and the config now correctly points at 57600 baud).
2. **Configure `FLTMODE_CH`** on the transmitter/FC for the RC-override
   design (docs plan M7/safety-case) - the one remaining piece before the
   safety-critical override chain is real, not just sim-tested.
3. Get a heatsink/fan for the Pi 5 before further sustained video-mode
   testing - confirmed running hot/marginal under combined AI+video load.
4. Real distance calibration (`tools/calibrate_camera.py` isn't written
   yet) and the M4 rangefinder hardware decision, before Follow/Approach-Test
   get anywhere near a real flight.
5. Mounting on the aircraft, weight/power/thermal checks, then the staged
   real-flight testing sequence in the plan (M14) - props-off bench first.

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
