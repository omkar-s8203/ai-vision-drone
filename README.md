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

## Offline operation

**No internet access is required to fly or operate this system.** The Pi
runs its own WiFi access point (`companion/config/network.yaml`'s
`mode: ap`) and the Android app connects to it directly; the control/
telemetry WebSocket and the WebRTC video link are both LAN-only, and
WebRTC is deliberately configured with no STUN/TURN servers on either end
(see `docs/protocol.md`) since two peers on the same self-hosted AP never
need one. AI detection runs on-sensor (IMX500) with no cloud inference,
MAVLink is a direct wired link to the FC, and the Android app has no
analytics or cloud SDKs. Internet is only ever needed for one-time setup
on a dev machine - `pip install`, `git clone`, flashing the Pi OS/IMX500
firmware, the first Gradle build - never for actual flight operation.

## Progress

**~70% - the companion computer is now mounted on the aircraft, the whole stack has run together on the mounted aircraft with props off, the Android app has been fully exercised live, and real camera-intrinsics calibration is done.** A Raspberry Pi 5 + AI Camera + Cube Orange flight controller are all wired together and talking, and `companion.main` has been run in hardware mode with the FC connected live - camera, on-sensor AI, video, and MAVLink all running together, with heartbeat, telemetry, arm/disarm, and flight-mode read/set all working against the real FC (**guidance setpoints - Follow/Orbit/Approach-Test - have not been sent to the real FC yet**, only administrative commands and telemetry so far). Live AI detection also went down and came back during this hardware phase: a field report of zero detections turned into a real three-pass root-cause saga (see M2 and `docs/hardware-wiring.md`), ending in `Picamera2IMX500Camera` switching from two separate `capture_metadata()`/`capture_array()` calls to a single `capture_request()` per frame - confirmed working live again. A heatsink/fan is now installed on the Pi 5. The Android app has now been fully exercised live against the real hardware companion session: connect, video, drag/tap target selection, the tracking overlay, arm/disarm, the flight-mode dropdown, the guidance-mode buttons, the obstacle-warning banner, the record-video timer, and the new phone-side `LocalVideoRecorder` (confirmed playable) all confirmed working on a physical phone. `tools/calibrate_camera.py` has been run against real checkerboard photos and `camera_calibration.yaml` now holds real fitted intrinsics, not placeholders. The companion computer is mounted on the aircraft and the plan's staged real-flight sequence (M14) has reached its first stage - bench, props off, confirming the full stack runs together on the actual mounted aircraft - stages 2 through 5 (tethered hover, free flight with tracking only, then Follow-mode flight, then Approach-Test flight) have not been attempted yet. Getting MAVLink working in the first place took a long debugging session whose actual root cause was a baud-rate mismatch (57600, not 921600 - the FC never actually adopted the GCS-configured baud despite the UI showing it applied) - see `docs/hardware-wiring.md` for the full story and every other real bug this hardware phase surfaced. Administrative GCS-style commands, Orbit and two Dronie/Parabola smart-shot guidance modes, a full DJI-Fly-style tabbed Android redesign, and a cross-mode obstacle-proximity safety trigger have all landed and been tested. RC-override transmitter configuration (`FLTMODE_CH`) and confirming the geofence signal against a real ArduPilot fence haven't happened yet.

| # | Milestone | Status | % |
|---|-----------|--------|---|
| M1 | Hardware Integration & Pi Setup | Pi 5 + AI Camera + flight controller all wired and confirmed working together, with a heatsink/fan installed for sustained AI+video thermal load. **The companion computer is now mounted on the aircraft**, and the full stack has been confirmed running together on the mounted aircraft with props off (M14 stage 1). Weight/thermal checks under that configuration and confirming operation off the actual flight battery (vs. bench power) still to be verified | 68% |
| M2 | AI Camera / Detection | **Confirmed live again after a real, three-pass debugging saga** - a field report of zero detections turned out to be `Picamera2IMX500Camera` calling `capture_metadata()` and `capture_array()` as two separate, independently-triggered captures per frame, which could desync which frame's metadata you got from which frame's image; switched to a single `capture_request()` per frame (metadata + image from the same underlying capture, guaranteed) and detection is confirmed working live in the Android app again. Two earlier fix attempts (a missing firmware-upload wait, then a call-ordering fix for it) were real, necessary fixes along the way but not the whole story - see `docs/hardware-wiring.md` for the full sequence, each step verified against real hardware via a standalone diagnostic script before being trusted | 90% |
| M3 | Tracking, Target Selection, Reacquisition | Implemented, unit-tested, confirmed live from a real phone (sim + now real camera). New appearance-based re-identification (`companion/tracking/appearance.py`, "AI learning mode"): a color-histogram signature is captured on target selection, and if the target is fully lost (not just the tracker's own short in-frame REACQUIRE window), new detections are matched against it each frame so the same target auto-relocks without a re-tap - unit- and integration-tested, hardware-only (needs real pixel data). ByteTrack swap-in still a stub | 88% |
| M4 | Distance Estimation | Vision (pinhole) estimator implemented + tested, now also feeding the obstacle-proximity safety check (M10). **`tools/calibrate_camera.py` has now been run against real checkerboard photos taken with the actual Pi camera** - `camera_calibration.yaml` holds real fitted intrinsics, not placeholder values. Rangefinder hardware addition still open (see plan) - now the natural next decision for this milestone since the vision-only path is fully calibrated | 75% |
| M5 | Video Streaming & Pi↔Android Comms | **Confirmed live on real hardware**: real camera video, correct colors, over real WebRTC/ICE to a real phone. Local on-Pi video recording (`VideoRecorder`, independent of the WebRTC feed) now implemented, unit-tested, and hardened against a real silent-failure codec bug. Real frame-rate bug found and fixed: the camera loop was double-pacing itself (a redundant `asyncio.sleep()` on top of the hardware capture call already blocking at the configured rate), halving a configured 30 FPS down to ~15 FPS observed - see hardware-wiring.md. GStreamer hardware-encode path still stubbed (current path is the CPU-heavy software-encode "quick bringup" one, which caused one crash on inadequate power) | 87% |
| M6 | Android Ground Station App | **Fully exercised live against the real hardware companion session**: connect, video, drag/tap target selection, the tracking overlay, arm/disarm, the flight-mode dropdown, the guidance-mode buttons, and the obstacle-warning banner are all confirmed working end-to-end on a physical phone against the actual running Pi (not sim). Real `gradle assembleDebug` succeeded and the app has run on a physical device across several rounds of changes (three real compile/layout errors found and fixed this way - see android/README.md). Restructured into a DJI-Fly-style 4-tab layout (Fly/Control/AI Modes/Settings), a tap-to-select quick action sheet, an orbit-ring overlay, a guidance-warning banner, and Dronie/Parabola mode buttons. **Fixed a real field-reported bug**: the record button's on-screen timer was frozen at 0:00 the whole time recording ran, because the Pi only ever sent the duration once at toggle time - **confirmed fixed live**, the timer now counts up correctly. **New**: `LocalVideoRecorder.kt` saves a second copy of the video locally on the phone itself (MediaCodec/MediaMuxer, MP4) alongside the Pi's own recording, from the same Record button - **confirmed live**, produces an actually-playable file on a real device | 93% |
| M7 | MAVLink / Flight-Controller / RC Override | **Real MAVLink link confirmed working with the full companion stack running**: heartbeat + 10Hz ATTITUDE over TELEM1 @ 57600 baud with a real Cube Orange, now confirmed alongside camera/video/AI in the same `companion.main` hardware-mode run (previously only proven separately). Administrative `arm()`/`set_mode()` commands confirmed against the real FC, not just the mock. `FLTMODE_CH` RC-override switch not yet configured on the transmitter - the software backstop (stick-deflection detection) is tested and working, but the actual hardware-independent guarantee this project is built around is not live yet. Guidance setpoints (Follow/Orbit/Approach-Test) have not been sent to the real FC yet. See `docs/safety-case.md` for the full breakdown | 85% |
| M8 | Follow / Orbit / Smart-Shot Modes | Follow controller implemented, unit + integration tested against mock FC, confirmed live end-to-end from the Android app including the live separation override (sim). `OrbitController` (circle/point-of-interest shot) and new `SmartShotController` (Dronie/Parabola one-shot cinematic moves) implemented and unit-tested. The Android guidance-mode buttons themselves (mode switching/UI) are now confirmed live against the real hardware companion, but no guidance controller has actually computed/sent a velocity setpoint to the real FC yet - the recent props-off bench session confirmed the stack runs together on the mounted aircraft but didn't engage guidance. The computed velocity setpoint for whichever controller is active, and whether it actually reached the FC, is now surfaced live in `tracking_update` and Android's new `GuidanceCommandPanel` - previously only visible after the fact in the Pi's session log - specifically so the next bench session has something to watch | 78% |
| M9 | Controlled Approach-Test | Controller + every abort condition implemented, unit-tested, confirmed live from the Android app (sim). Geofence abort now reads a real `MavlinkBridge.telemetry.fence_breached` (parsed from a real `SYS_STATUS` message via pymavlink's own `MAV_SYS_STATUS_GEOFENCE` bit) instead of a hardcoded `False` - verified against a real mock FC and the full orchestrator, but not yet against a real ArduPilot FC. Fence status is also now surfaced live in the `telemetry` message and the Android `TelemetryPanel`, not just after the fact via an abort's `guidance_reason` | 76% |
| M10 | Safety Architecture & Watchdog | Supervisor + heartbeat/systemd watchdogs implemented, fault-injection-style unit tests passing, abort's reset-to-idle confirmed live (sim). Cross-mode obstacle-proximity guard (`companion/safety/proximity_guard.py`): any detected object closer than `min_obstacle_distance_m`, not just the tracked target, forces the Supervisor to SAFE - unit-tested, and surfaced to the operator via a visible warning banner in the Android app. **`docs/safety-case.md` now written** - mechanism/trigger/guarantee/test for every gate, including the honest remaining gaps (`FLTMODE_CH` not configured; geofence wired but not confirmed against real ArduPilot) | 85% |
| M11 | Logging | Structured JSON logging (rotates via `RotatingFileHandler`) + session recorder implemented and wired in. **Fixed a real gap**: `SessionRecorder` created a new timestamped session file every run but never cleaned up old ones - unlike `companion.log`, they accumulated forever on the Pi's finite disk, exactly the risk the plan's own M11 testing section calls out. Now prunes to the most recent 50 sessions by default, unit-tested (`test_session_recorder.py`, previously had zero direct tests despite being used as test infrastructure everywhere) | 78% |
| M12 | Performance Optimization | Not started (deliberately deferred until correctness is proven, per plan) | 0% |
| M13 | Testing Strategy & Simulation-Before-Flight | Synthetic target generator + mock flight controller + full end-to-end integration tests all passing (175/175 tests), backed by live device tests (sim) and live hardware tests (real camera/detection/video/MAVLink). A real end-to-end test drives the actual JSON wire protocol over a real WebSocket + real MAVLink to a real (mock) FC (`test_integration_websocket.py`) - every other integration test used an in-process fake transport, so this is the first automated proof the wire protocol itself works; `MockFlightController` now also reflects real arm/set-mode/geofence-status MAVLink messages, not just guidance setpoints. Also fixed a real bug in the test suite itself: its `recv_envelope_of_type` helper could return a stale, superseded message instead of the one just produced, since it returned the first match found rather than the latest - now fixed to drain to the freshest matching message | 87% |
| M14 | Real-Flight Testing Stages | **Stage 1 reached**: bench, props off - the companion computer is mounted on the aircraft, and the full stack (camera, AI, video, MAVLink) has been confirmed running together on the mounted aircraft with props off. Stage 2 (tethered/ground hover, Normal RC, Pi passive) through stage 5 (Approach-Test flight) not yet attempted - each stage's own go/no-go review happens before the next, per the plan | 15% |
| M15 | Deployment & Monitoring | Orchestrator runs standalone (`python -m companion.main`) in both sim and hardware mode, confirmed on real Pi. Systemd unit (`deploy/ai-vision-drone.service`) now written - auto-starts on boot, `Restart=on-failure` on crash - see INSTALL.md step 7a. Not yet confirmed surviving an actual power-cycle test on the Pi | 55% |
| M16 | Future Scalability | Design notes only (not implementation-gated) | n/a |

Test suite: `.venv/Scripts/python -m pytest -q` → 175 passed. Android: real
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

1. ~~Finish functionally verifying the Android app against the live hardware companion~~ -
   done: connect, video, drag/tap target selection, the tracking overlay,
   arm/disarm, the flight-mode dropdown, the guidance-mode buttons, and the
   obstacle-warning banner are all confirmed working live against the real
   running Pi. The record-video timer fix is confirmed counting up
   correctly, and the new phone-side `LocalVideoRecorder` is confirmed
   producing an actually-playable file on a real device.
2. ~~AI detection stopped producing any results on real hardware~~ - fixed
   for real after a three-pass debugging saga (see M2, `docs/
   hardware-wiring.md`): `Picamera2IMX500Camera` now uses a single
   `capture_request()` per frame instead of two separate, independently-
   triggered `capture_metadata()`/`capture_array()` calls that could desync
   which frame's metadata matched which frame's image. Confirmed live in
   the Android app. Detection scores as low as 0.44-0.56 were seen during
   root-causing this against real, genuine subjects - keep
   `camera.score_threshold` (`hardware.yaml`, default 0.5) in mind if
   detection feels inconsistent under different lighting/angle/blur
   conditions; lowering it to ~0.3 is a one-line config change, not a code
   change.
3. **Send real guidance setpoints to the real FC** - the M14 stage 1
   bench session (props off, on the mounted aircraft) confirmed the whole
   stack runs together, but didn't engage a guidance mode yet. What hasn't
   happened yet is a guidance controller (Follow/Orbit/Approach-Test)
   actually computing and sending a velocity setpoint to the real FC -
   this is the natural next step for that same bench setup, now watching
   the live dashboard (`tracking_update`'s `commanded_*`/`guidance_sent`
   fields, rendered by Android's `GuidanceCommandPanel`) while a guidance
   mode is actually engaged, props still off.
4. **Configure `FLTMODE_CH`** on the transmitter/FC for the RC-override
   design (docs plan M7, `docs/safety-case.md`) - the one remaining piece
   before the safety-critical override chain is real, not just sim-tested.
5. **Confirm the geofence signal against a real ArduPilot FC** - the wiring
   itself is done (`companion/main.py` now reads a real `MavlinkBridge.
   telemetry.fence_breached`, parsed from `SYS_STATUS` via pymavlink's own
   `MAV_SYS_STATUS_GEOFENCE` bit), and verified against a real mock FC over
   real MAVLink, but a mock only proves the code reacts correctly to bits
   it expects - it doesn't prove a real Cube Orange reports geofence status
   the same way. Enable `FENCE_ENABLE` on the bench and confirm
   `telemetry.fence_breached` actually flips when the boundary is crossed,
   the same way the TELEM baud-rate assumption once turned out wrong until
   real hardware proved otherwise (see `docs/hardware-wiring.md`).
6. ~~Get a heatsink/fan for the Pi 5 before further sustained video-mode
   testing~~ - done, now installed.
7. ~~Run `tools/calibrate_camera.py` against real checkerboard photos taken
   with the actual Pi camera~~ - done: `camera_calibration.yaml` now holds
   real fitted intrinsics. The M4 rangefinder hardware decision is still
   open (see plan) - worth deciding before Follow/Approach-Test get
   anywhere near a real flight, since the boundary/separation checks
   currently rest on the vision-only estimate this calibration feeds.
8. ~~Mounting on the aircraft~~ - done, and the staged real-flight testing
   sequence (M14) has reached its first stage: bench, props off, full
   stack confirmed running together on the mounted aircraft. Weight/
   power/thermal checks under that configuration still to be confirmed,
   then stage 2 (tethered/ground hover, Normal RC, Pi passive) through
   stage 5 (Approach-Test flight) - each with its own go/no-go review
   before the next, per the plan.

See `docs/protocol.md`, `docs/safety-case.md`, and `docs/hardware-wiring.md` for the specs that get filled in as each milestone lands.
