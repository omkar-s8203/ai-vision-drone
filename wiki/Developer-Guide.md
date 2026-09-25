# Developer Guide

## Setting up

```bash
git clone https://github.com/omkar-s8203/ai-vision-drone.git
cd ai-vision-drone
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[video,dev]"
python -m pytest -q                  # 763 passed, 2 skipped
python -m companion.main             # sim mode - connect the app to this machine's IP
```

Python 3.11+ (3.12 used). `picamera2` only exists on the Pi; everything else runs anywhere. Hardware classes are mocked in tests.

For the app, open `android/` in Android Studio (JDK 17+, Android SDK).

## Code map

```
companion/
  main.py                 CompanionOrchestrator (per-frame cycle), builders for sim/hardware,
                          startup health check, _amain() entry point
  vision/
    camera.py             Picamera2IMX500Camera (capture thread, stall detection), SyntheticCamera
    detector.py           BBox, Detection, IMX500Detector, PassthroughDetector, labels loading
  tracking/
    base.py               Tracker interface, TrackedTarget (bbox + guidance_bbox)
    state.py              TrackingStateMachine: IDLE/TRACKING/REACQUIRE/TARGET_LOST, coast()
    iou_tracker.py        default tracker
    bytetrack_impl.py     two-stage tracker
    motion.py             alpha-beta motion filter, matching helpers
    appearance.py         colour-histogram identity check and re-lock
    target_selector.py    tap / drag → detection
  guidance/
    command.py            GuidanceCommand (vx, vy, vz, yaw rate)
    follow.py, orbit.py   controllers
    approach_test.py      bounded approach with abort conditions
    grid_search.py        lawnmower sweep
    target_recovery.py    search → RTL / operator-confirmed land
    auto_takeoff.py       Arm & Follow sequencer
    distance.py           pinhole estimate, DistanceFilter, DistanceEstimator
    rangefinder.py        TFmini-S driver
    pid.py, limits.py     PID, slew limiter, altitude limits, clamps
    geo.py                haversine, bearing, destination point, lawnmower waypoints
  safety/
    supervisor.py         SafetySupervisor - the single gate
    watchdog.py           HeartbeatWatchdog (subsystems), SystemdWatchdog + sd_notify
    proximity_guard.py    obstacle check
    contact_sensor.py     contact sensor interface (null by default)
  mavlink/
    bridge.py             MavlinkBridge: telemetry, commands, mode confirmation, reconnect
    rc_monitor.py         stick-override detection
  comms/
    transport.py          WebSocketTransport (per-client queues)
    ws_server.py          GroundStationLink: dispatch, send helpers, liveness
    protocol.py           envelope and message types
    video_pipeline.py     aiortc pipeline (default), GStreamer draft, latency overlay
    video_recorder.py     Pi-side recording on its own thread
  learning/               Teach mode: visual tracker, dataset recorder, taught-object registry
  logging_/               JSON logging, SessionRecorder (JSONL events)
  config/                 YAML files + loader
  tests/                  pytest suite
sim/                      mock FC, SITL harness, synthetic target
tools/                    see the Tools page
deploy/                   systemd unit
android/                  Kotlin app
docs/                     protocol, safety case, wiring, lab checklist, Teach guide
```

## Rules the codebase follows

1. **Controllers never touch MAVLink.** They return a `GuidanceCommand`; the Supervisor decides. A new guidance path must go through `SafetySupervisor.evaluate()`.
2. **Direct FC mode changes** (RTL, LAND, BRAKE, LOITER, GUIDED) are outside the Supervisor, so every new one must: check `mavlink.is_connected`, skip while `rc_monitor.is_overriding(...)`, and never fight a mode the pilot chose.
3. **Nothing blocks the event loop.** Slow work (OpenCV trackers, file writes, video encoding, camera capture, MAVLink reads) runs on threads. Awaiting `run_in_executor` inside `process_frame()` still stalls *that* coroutine - use fire-and-forget workers for per-frame work.
4. **Long-lived loops isolate bad items.** One malformed message or frame is logged and skipped, never allowed to kill the loop.
5. **Every app-supplied value is untrusted.** Clamp to config bounds, ignore non-finite numbers, slugify names.
6. **Unknown or stale data fails closed.** Missing altitude → no descent; missing GPS → no Grid Search; stale subsystem → SAFE.
7. **Tell the operator.** A refusal sets `guidance_reason`; a deliberate hold sets `guidance_hold`; one-shot outcomes (arm, mode, teach) get their own message.
8. **Comments explain why**, often with the field report or audit that motivated them. Keep that density when you change nearby code.
9. **Be honest about verification.** Docs say "tested against the mock FC" vs "confirmed on hardware" explicitly. Do not upgrade a claim without evidence.

## Common changes

### Adding a config key

1. Add it to the YAML with a comment explaining it.
2. Read it where it is used.
3. If it is safety-relevant, add it to `run_startup_health_check()` (with a range via `_require_number` where a typo would be dangerous) and to the complete-config fixtures in `test_startup_health_check.py`.
4. Add a test that the value is threaded to its user (`test_safety_parameters.py` shows the pattern).
5. Document it on the [Configuration Reference](Configuration-Reference).

### Adding a guidance mode

1. Controller in `guidance/` returning `GuidanceCommand`.
2. A `SupervisorState`, an entry in `MODE_COMMAND_MAP` (it then automatically triggers the GUIDED request), and the allowed list in `SafetySupervisor.evaluate()`. Decide deliberately whether target loss should block it.
3. Dispatch in `process_frame()`; make sure controllers that did not run are reset.
4. Reset or cancel it in `_on_mode_command()` and `_on_abort()`.
5. App: mode button, alerts (`AlertEvent`, `emitTrackingAlerts()`), `ONE_SHOT_MODES` if it finishes by itself.
6. Update `docs/protocol.md`, `docs/safety-case.md`, the lab checklist.

### Adding a message type

Add it to `companion/comms/protocol.py` **and** `android/.../comms/Protocol.kt`, a send helper or handler in `ws_server.py`, the app handler in `MainViewModel`, and `docs/protocol.md`.

## Documents to keep current

| Document | Update when |
|---|---|
| `docs/safety-case.md` | Any safety-relevant mechanism changes (a stale entry is worse than none) |
| `docs/protocol.md` | Any message or field changes |
| `docs/lab-test-checklist.md` | Any behaviour that needs bench verification |
| `README.md` | Milestone status, test count |
| This wiki | User-visible behaviour, config, setup |

## Deploying

Push to `master`, then on the Pi: `git pull`, `pip install -e ".[video]"`, restart the service (and re-copy the unit if `deploy/` changed). See [Installation → Updating](Installation#9-updating).
