from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuidanceCommand:
    """Body-frame velocity setpoint proposed by a guidance controller.

    Never sent to the flight controller directly by the controller that
    produced it - it must pass through the Safety Supervisor gate first
    (companion/safety/supervisor.py), which is the only module allowed to
    hand it to the MAVLink bridge.
    """

    vx_mps: float  # forward/back, +forward
    vy_mps: float  # right/left, +right
    vz_mps: float  # down/up, +down (MAVLink NED convention)
    yaw_rate_rads: float
