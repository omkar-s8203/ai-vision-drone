# AI Vision Drone

Companion-computer vision/AI upgrade for an existing, already-flying RC drone (RC → receiver → flight controller (ArduPilot) → ESCs → motors — unchanged). Adds a Raspberry Pi 5 + Raspberry Pi AI Camera as a vision/AI companion computer, and a native Android Ground Station app, without replacing the flight controller or taking direct motor control.

**Setting up real hardware? Start with [INSTALL.md](INSTALL.md)** - a
from-scratch guide covering OS flashing, camera/AI stack, flight-controller
wiring, power supply requirements, and the Android app.

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

**~66% - camera, AI, video, and MAVLink are all confirmed working end-to-end on real hardware, and the Android app now has a real, build-verified rewrite.** A Raspberry Pi 5 + AI Camera + Cube Orange flight controller are now all wired together and talking: real on-sensor SSD MobileNetV2 detection, real video streamed over WebRTC to a real Android phone, and real MAVLink (heartbeat + 10Hz ATTITUDE) over TELEM1. Getting MAVLink working took a long debugging session whose actual root cause was a baud-rate mismatch (57600, not 921600 - the FC never actually adopted the GCS-configured baud despite the UI showing it applied) - see `docs/hardware-wiring.md` for the full story and every other real bug this hardware phase surfaced. Administrative GCS-style commands (arm/disarm, flight-mode change, local video recording), Orbit and two Dronie/Parabola smart-shot guidance modes (DJI "circle"/"QuickShot" equivalents), a full DJI-Fly-style tabbed Android redesign, and a cross-mode obstacle-proximity safety trigger have all landed and been tested (Python: fully unit-tested; Android: real `gradle assembleDebug` succeeded and the app has run on a physical device, though not yet exercised against a live companion session). Mounting on the aircraft and RC-override transmitter configuration haven't happened yet.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Pi 5 + AI Camera + flight controller all wired and confirmed working together on a bench. Drone mounting, flight-battery power source, and weight/thermal checks not done yet | 50% |
| M2 | AI Camera / Detection | **Confirmed on real hardware** end-to-end through our own code, not a demo script | 85% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented, unit-tested, confirmed live from a real phone (sim + now real camera). New appearance-based re-identification (`companion/tracking/appearance.py`, "AI learning mode"): a color-histogram signature is captured on target selection, and if the target is fully lost (not just the tracker's own short in-frame REACQUIRE window), new detections are matched against it each frame so the same target auto-relocks without a re-tap - unit- and integration-tested, hardware-only (needs real pixel data). ByteTrack swap-in still a stub | 88% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested, now also feeding the obstacle-proximity safety check (M10). `tools/calibrate_camera.py` written and unit-tested (checkerboard-based intrinsics fit, matches `CameraIntrinsics`/`camera_calibration.yaml` exactly) - not yet run against real Pi camera photos, so the config still holds placeholder values. Rangefinder hardware addition still open (see plan) | 62% |
| M5 | Video Streaming & Pi↔Android Comms | **Confirmed live on real hardware**: real camera video, correct colors, over real WebRTC/ICE to a real phone. Local on-Pi video recording (`VideoRecorder`, independent of the WebRTC feed) now implemented, unit-tested, and hardened against a real silent-failure codec bug. Real frame-rate bug found and fixed: the camera loop was double-pacing itself (a redundant `asyncio.sleep()` on top of the hardware capture call already blocking at the configured rate), halving a configured 30 FPS down to ~15 FPS observed - see hardware-wiring.md. GStreamer hardware-encode path still stubbed (current path is the CPU-heavy software-encode "quick bringup" one, which caused one crash on inadequate power) | 87% |
| M6 | Android Ground Station App | **Build-verified**: real `gradle assembleDebug` succeeded and the app has been installed and running on a physical device across several rounds of changes (three real compile/layout errors found and fixed this way - see android/README.md). Restructured into a DJI-Fly-style 4-tab layout (Fly/Control/AI Modes/Settings), a tap-to-select quick action sheet, an orbit-ring overlay, a guidance-warning banner, and Dronie/Parabola mode buttons. Not yet functionally verified against a live companion session (sim or hardware) | 83% |
| M7 | MAVLink / Flight-Controller / RC Override | **Real MAVLink link confirmed working**: heartbeat + 10Hz ATTITUDE over TELEM1 @ 57600 baud with a real Cube Orange. Administrative `arm()`/`set_mode()` commands added and unit-tested, wired end-to-end from the Android arm/mode controls through `GroundStationLink`/`CompanionOrchestrator`, and now verified over a real WebSocket+MAVLink chain, not just mocks. `FLTMODE_CH` RC-override switch not yet configured on the transmitter - the software backstop (stick-deflection detection) is tested and working, but the actual hardware-independent guarantee this project is built around is not live yet. See `docs/safety-case.md` for the full breakdown | 83% |
| M8 | Follow / Orbit / Smart-Shot Modes | Follow controller implemented, unit + integration tested against mock FC, confirmed live end-to-end from the Android app including the live separation override (sim). `OrbitController` (circle/point-of-interest shot) and new `SmartShotController` (Dronie/Parabola one-shot cinematic moves) implemented, unit-tested, and build-verified on the Android side (none of the three yet functionally tested live) | 74% |
| M9 | Controlled Approach-Test | Controller + every abort condition implemented, unit-tested, confirmed live from the Android app (sim). Geofence abort now reads a real `MavlinkBridge.telemetry.fence_breached` (parsed from a real `SYS_STATUS` message via pymavlink's own `MAV_SYS_STATUS_GEOFENCE` bit) instead of a hardcoded `False` - verified against a real mock FC and the full orchestrator, but not yet against a real ArduPilot FC. Fence status is also now surfaced live in the `telemetry` message and the Android `TelemetryPanel`, not just after the fact via an abort's `guidance_reason` | 76% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing, abort's reset-to-idle confirmed live (sim). Cross-mode obstacle-proximity guard (`companion/safety/proximity_guard.py`): any detected object closer than `min_obstacle_distance_m`, not just the tracked target, forces the Supervisor to SAFE - unit-tested, and surfaced to the operator via a visible warning banner in the Android app. **`docs/safety-case.md` now written** - mechanism/trigger/guarantee/test for every gate, including the honest remaining gaps (`FLTMODE_CH` not configured; geofence wired but not confirmed against real ArduPilot) | 85% |
| M11 | Logging | Structured JSON logging + session recorder implemented and wired in | 70% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (163/163 tests), backed by live device tests (sim) and live hardware tests (real camera/detection/video/MAVLink). A real end-to-end test drives the actual JSON wire protocol over a real WebSocket + real MAVLink to a real (mock) FC (`test_integration_websocket.py`) - every other integration test used an in-process fake transport, so this is the first automated proof the wire protocol itself works; `MockFlightController` now also reflects real arm/set-mode/geofence-status MAVLink messages, not just guidance setpoints. Also fixed a real bug in the test suite itself: its `recv_envelope_of_type` helper could return a stale, superseded message instead of the one just produced, since it returned the first match found rather than the latest - now fixed to drain to the freshest matching message | 87% |
| M14 | Real-Flight Testing Stages | Not started - blocked on drone mounting | 0% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`) in both sim and hardware mode, confirmed on real Pi. Systemd unit (`deploy/ai-vision-drone.service`) now written - auto-starts on boot, `Restart=on-failure` on crash - see INSTALL.md step 7a. Not yet confirmed surviving an actual power-cycle test on the Pi | 55% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 163 passed. Android: real
`gradle assembleDebug` builds clean; the app has run on a physical device
(Android SDK/Gradle distribution found locally and used directly, bypassing
the earlier "no Android SDK here" limitation). First real-device usage
feedback (from a remote-controller-mounted display, not just this dev
machine) also landed and got fixed: clipped/hidden buttons from
fixed-width layouts (now full-width stacks or scrollable rows throughout),
video recording moved to a dedicated main-screen button, settings
persistence, a real `cv2.VideoWriter` silent-failure bug in the recording
backend, and a real frame-rate bug (a redundant sleep was halving a
configured 30 FPS down to ~15 FPS).

## What's next

1. **Functionally verify the Android app itself against a live companion** -
   a real WebSocket/MAVLink client (this test suite's new
   `test_integration_websocket.py`) now proves the *protocol and backend*
   work end-to-end, but the Android app's own UI (4-tab layout,
   Orbit/Dronie/Parabola modes, target action sheet, arm/disarm,
   flight-mode dropdown, record-video toggle, obstacle-warning banner) is
   still only build-verified, not exercised live (connect the real app to
   `COMPANION_MODE=sim` and walk through each tab for real).
2. **Run `companion.main` in hardware mode with the FC actually connected** -
   so far we've only proven the camera/video path and the MAVLink link
   separately; running them together is the next real integration test
   (and the config now correctly points at 57600 baud).
3. **Configure `FLTMODE_CH`** on the transmitter/FC for the RC-override
   design (docs plan M7, `docs/safety-case.md`) - the one remaining piece
   before the safety-critical override chain is real, not just sim-tested.
4. **Confirm the geofence signal against a real ArduPilot FC** - the wiring
   itself is done (`companion/main.py` now reads a real `MavlinkBridge.
   telemetry.fence_breached`, parsed from `SYS_STATUS` via pymavlink's own
   `MAV_SYS_STATUS_GEOFENCE` bit), and verified against a real mock FC over
   real MAVLink, but a mock only proves the code reacts correctly to bits
   it expects - it doesn't prove a real Cube Orange reports geofence status
   the same way. Enable `FENCE_ENABLE` on the bench and confirm
   `telemetry.fence_breached` actually flips when the boundary is crossed,
   the same way the TELEM baud-rate assumption once turned out wrong until
   real hardware proved otherwise (see `docs/hardware-wiring.md`).
5. Get a heatsink/fan for the Pi 5 before further sustained video-mode
   testing - confirmed running hot/marginal under combined AI+video load.
6. **Run `tools/calibrate_camera.py` against real checkerboard photos taken
   with the actual Pi camera** (the tool itself is written and tested, just
   never run against real hardware images) and make the M4 rangefinder
   hardware decision, before Follow/Approach-Test get anywhere near a real
   flight.
7. Mounting on the aircraft, weight/power/thermal checks, then the staged
   real-flight testing sequence in the plan (M14) - props-off bench first.

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
