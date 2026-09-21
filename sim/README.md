# Simulation Harness

Status: implemented (M13 — Testing Strategy & Simulation-Before-Flight).

Contents:
- `mock_fc.py` — `MockFlightController`, a lightweight MAVLink stand-in for ArduPilot SITL (default path — no Linux/WSL2 build environment needed). Used by `companion.main.build_sim_orchestrator()` and most integration tests.
- `sitl_harness.py` — `get_flight_controller_harness()` picks `MockFlightController` by default, or launches real ArduPilot SITL (`sim_vehicle.py`) via `RealSitlHarness` when it's found on PATH (needs a Linux/WSL2 build environment with ArduPilot already built). `RealSitlHarness` exposes a `.connection` MAVLink endpoint string, `wait_ready()` (blocks until SITL emits a real heartbeat), and `stop()`/context-manager cleanup that kills the whole `sim_vehicle.py` process group, not just its parent PID. Only ever exercises real SITL when the environment actually has it — see `sim/tests/test_sitl_harness.py`, which mocks the subprocess/OS calls so the launch logic itself is tested without needing SITL installed.
- `synthetic_target.py` — `SyntheticTargetGenerator`/`render_frame`, generating synthetic detections/video frames simulating a moving target, for testing tracking, distance estimation, follow, and approach-test logic without a real camera. Used by `build_sim_orchestrator()`.
