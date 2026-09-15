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

**~45% toward a fully-simulated, hardware-ready system.** Build order has been: full companion (Pi-side) code first, using mock/synthetic implementations for anything hardware-dependent, then a simulation harness, then integration, then the Android app skeleton. Real hardware bring-up (M1, M14) hasn't started - everything else below runs and is tested (Pi side) or at least code-complete (Android side) entirely in software.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Not started - blocked on physical hardware | 0% |
| M2 | AI Camera / Detection | Interfaces + sim path done (`SyntheticCamera`, `IMX500Detector`); untestable until real camera | 40% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented + unit-tested (IOU tracker, state machine, selector). ByteTrack swap-in still a stub | 80% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested. Rangefinder hardware addition still open (see plan) | 50% |
| M5 | Video Streaming & Pi↔Android Comms | WebSocket control/telemetry/WebRTC-signaling channel done + tested. `AiortcVideoPipeline` verified end-to-end against a real aiortc peer over loopback and wired into sim mode - telemetry/health now actually sent every frame. GStreamer hardware-encode path still stubbed | 65% |
| M6 | Android Ground Station App | Code-complete Kotlin skeleton (video render, target selection, tracking overlay, mode controls, telemetry/health panels, abort) - **not yet build-verified**, no Android SDK in this dev environment (see `android/README.md`) | 45% |
| M7 | MAVLink / Flight-Controller / RC Override | Bridge + RC-override monitor implemented; integration-tested end-to-end against a mock flight controller | 60% |
| M8 | Follow-Mode | Controller implemented, unit + integration tested against mock FC. Real gain tuning pending | 55% |
| M9 | Controlled Approach-Test | Controller + every abort condition (target-loss, comms-loss, RC-override, geofence, no-distance) implemented and unit-tested | 55% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing | 70% |
| M11 | Logging | Structured JSON logging + session recorder implemented and wired in | 70% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (63/63 tests) | 65% |
| M14 | Real-Flight Testing Stages | Not started - blocked on physical hardware | 0% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`), now with video included; systemd unit file not yet written | 30% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 63 passed.

## What's next

1. **Verify the Android build** - open `android/` in Android Studio to resolve dependencies and fix whatever the compiler finds (most likely the `org.webrtc.*` API surface - see `android/README.md`'s known gaps). This is the main remaining unknown, since it's the one piece not testable from this environment.
2. Once you have the Pi 5 + AI Camera + flight controller in hand, M1 (hardware bring-up) and M2/M7 hardware-mode testing become unblocked.
3. Smaller follow-ups tracked in `android/README.md`'s "Known gaps" (live follow-separation override, WS reconnect logic) and `docs/protocol.md` (health metrics are still placeholder `null`s pending M12 instrumentation).

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
