# Simulation Harness

Status: not yet implemented — planned for M13 (Testing Strategy & Simulation-Before-Flight), built early alongside M2/M3 so the full companion stack can be exercised without real hardware.

Planned contents:
- `sitl_harness.py` — spins up ArduPilot SITL and connects the companion MAVLink bridge to it.
- `synthetic_target.py` — generates synthetic detections/video frames simulating a moving target, for testing tracking, distance estimation, follow, and approach-test logic without a real camera.
