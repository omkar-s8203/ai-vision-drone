from __future__ import annotations

import shutil

from sim.mock_fc import MockFlightController


def get_flight_controller_harness(prefer_real_sitl: bool = True) -> MockFlightController:
    """Returns a running-FC-like object for integration testing.

    Real ArduPilot SITL needs a Linux build environment (WSL2 on Windows)
    and isn't assumed to be present. MockFlightController is the default so
    the companion MAVLink bridge, RC-override handling, and safety
    supervisor can be exercised without it. Swap in real SITL (sim_vehicle.py)
    once available - the companion bridge only needs a MAVLink UDP endpoint,
    so nothing else in the codebase has to change.
    """
    if prefer_real_sitl and shutil.which("sim_vehicle.py"):
        raise NotImplementedError(
            "Real ArduPilot SITL detected on PATH but the launch harness for it "
            "hasn't been written yet - use MockFlightController for now."
        )
    return MockFlightController()
