# Simulation and Testing

## Running the test suite

From the repo root on a development machine:

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Linux/macOS
pip install -e ".[video,dev]"
python -m pytest -q
```

Expected today: **763 passed, 2 skipped**. The two skips are Unix-socket `sd_notify` tests that only run on Linux (they were verified on Linux/WSL). Pytest settings live in `pyproject.toml` (`testpaths = companion/tests, sim/tests`, `asyncio_mode = auto`). A full run takes about a minute.

Run one area:

```bash
python -m pytest -q companion/tests/test_safety_supervisor.py
python -m pytest -q -k "reconnect or watchdog"
```

## What the tests cover

| Area | Examples |
|---|---|
| Safety gate | `test_safety_supervisor.py` - each gate tripped on its own; `test_failsafes_and_freshness.py` - link liveness, failsafe RTL, stale telemetry, GPS gating, stalls |
| Orchestrator behaviour | `test_tracking_safety_orchestrator.py` - clamps, holds, identity swap/drop on real pixels, AI-result carry-over; `test_admin_commands.py` - STOP/BRAKE, arm, force disarm |
| Tracking | `test_state_machine.py`, `test_iou_tracker.py`, `test_bytetrack_impl.py`, `test_motion_model.py`, `test_identity_check.py`, `test_appearance*.py`, `test_target_selector.py` |
| Guidance | `test_follow_controller.py`, `test_orbit_controller.py`, `test_guidance_limits.py`, `test_grid_search_*.py`, `test_auto_takeoff*.py`, `test_target_recovery*.py`, `test_approach_*.py` |
| Distance | `test_distance*.py`, `test_rangefinder.py` |
| MAVLink | `test_mavlink_bridge*.py`, `test_mavlink_reconnect.py`, `test_mode_confirmation.py`, `test_mock_fc.py` (real MAVLink over UDP to the mock FC) |
| Comms | `test_ws_server.py`, `test_protocol.py`, `test_transport_slow_client.py`, `test_integration_websocket.py` (real WebSocket + real MAVLink end to end) |
| Process health | `test_camera_stall.py`, `test_service_watchdog.py`, `test_startup_health_check.py`, `test_safety_parameters.py` |
| Video and recording | `test_video_pipeline.py`, `test_integration_video.py` (real aiortc peer), `test_video_recorder.py` |
| Teach mode | `test_teach_mode.py` (real OpenCV trackers on synthetic video; skipped without an OpenCV tracker) |
| Tools | `test_benchmark_detection.py`, `test_detection_regression.py`, `test_calibrate_camera.py`, `test_distance_validation.py`, `test_ws_latency_benchmark.py`, `test_live_monitor.py`, `test_export_taught_dataset.py`, `test_imx500_convert.py` |
| Sim harness | `sim/tests/test_sitl_harness.py` |

"Fault injection" here means a test that trips exactly one condition and asserts guidance is denied.

## Sim mode

```bash
python -m companion.main          # COMPANION_MODE defaults to sim
```

- `SyntheticCamera` produces a frame clock at 30 FPS; `SyntheticTargetGenerator` (`sim/synthetic_target.py`) moves a synthetic person, and `render_frame()` draws it for the video feed.
- `MockFlightController` (`sim/mock_fc.py`) is an in-process MAVLink stand-in on UDP 14550. It starts in GUIDED and armed, sends heartbeats, position, GPS, battery, `SYS_STATUS` (geofence) and `HOME_POSITION`, and accepts arm, mode and setpoints.
- The WebSocket server runs for real, so the Android app can connect to the laptop's IP.

It emulates only what this project needs - it is not ArduPilot.

## Real ArduPilot SITL

`sim/sitl_harness.py`: `get_flight_controller_harness()` returns the mock FC by default, or launches real SITL (`sim_vehicle.py`) via `RealSitlHarness` when it is on `PATH`. That needs a Linux or WSL2 environment with ArduPilot built.

- `wait_ready()` blocks until a genuine heartbeat (boot can take ~2 minutes).
- `stop()` / context-manager exit kills the whole process group, not just the parent.

No SITL run of this project has happened yet (lab checklist Stage 11).

## Android tests

Instrumented Compose tests in `android/app/src/androidTest/`: STOP is reachable on every tab, mode controls, flight dock, drag gesture. Run with `./gradlew connectedAndroidTest` on a device. Not yet run.

## What tests do not prove

Everything MAVLink-related beyond telemetry and admin commands is proven against the mock FC, not real ArduPilot: guidance setpoints, the geofence bit, BRAKE/RTL/LAND behaviour, takeoff. The bench stages in [Lab Testing](Lab-Testing-and-Flight-Readiness) exist to close that gap.
