from __future__ import annotations

import math
from typing import Optional

from companion.guidance.command import GuidanceCommand
from companion.guidance.pid import Pid
from companion.tracking.base import TrackedTarget


class OrbitController:
    """Computes a velocity setpoint to circle the tracked target at a
    configured radius - the DJI "Point of Interest"/circle-shot equivalent
    (docs plan M8 follow-mode architecture, extended). Never touches
    MAVLink - output is a GuidanceCommand for the Safety Supervisor to gate,
    same as FollowController.

    Approach mirrors FollowController rather than computing true GPS-relative
    bearing: forward/back (vx) holds the configured radius via a distance
    PID exactly like Follow's separation hold, and a constant tangential
    strafe (vy) sized from the current distance estimate and the configured
    angular speed sweeps the drone around the target. Yaw keeps the target
    centered in frame via the same lateral-pixel PID as Follow, which is
    what actually keeps the camera pointed at the subject while it strafes.
    This is a deliberate simplification (no real bearing/GPS geometry) -
    consistent with the project's priority order (STABLE > LOW LATENCY >
    ACCURATE) and easy to unit test without a real position source.
    """

    def __init__(self, limits: dict) -> None:
        self.limits = limits
        pid_cfg = limits["pid"]
        self._distance_pid = Pid(**pid_cfg["distance"], out_limit=limits["max_speed_mps"])
        self._lateral_pid = Pid(**pid_cfg["lateral"], out_limit=1.0)  # rad/s
        self._vertical_pid = Pid(**pid_cfg["vertical"], out_limit=limits["max_speed_mps"])
        altitude_pid_cfg = pid_cfg.get("altitude", pid_cfg["vertical"])
        self._altitude_pid = Pid(**altitude_pid_cfg, out_limit=limits["max_speed_mps"])

    def reset(self) -> None:
        self._distance_pid.reset()
        self._lateral_pid.reset()
        self._vertical_pid.reset()
        self._altitude_pid.reset()

    def compute(
        self,
        target: TrackedTarget,
        distance_m: Optional[float],
        image_width: int,
        image_height: int,
        dt: float,
        current_altitude_m: Optional[float] = None,
    ) -> GuidanceCommand:
        max_speed = self.limits["max_speed_mps"]

        vx = 0.0
        if distance_m is not None:
            distance_error = distance_m - self.limits["orbit_radius_m"]
            vx = self._distance_pid.step(distance_error, dt)
            vx = max(-max_speed, min(max_speed, vx))

        direction = self.limits.get("direction", 1)
        angular_speed_rad_s = math.radians(self.limits["angular_speed_dps"]) * direction
        orbit_radius = distance_m if distance_m is not None else self.limits["orbit_radius_m"]
        vy = angular_speed_rad_s * orbit_radius
        vy = max(-max_speed, min(max_speed, vy))

        lateral_error_px = target.bbox.cx - image_width / 2
        if abs(lateral_error_px) < self.limits["lateral_deadband_px"]:
            lateral_error_px = 0.0
        yaw_rate = self._lateral_pid.step(lateral_error_px, dt)

        target_altitude_m = self.limits.get("target_altitude_m")
        if target_altitude_m is not None and current_altitude_m is not None:
            altitude_error = target_altitude_m - current_altitude_m
            vz = -self._altitude_pid.step(altitude_error, dt)  # NED: negative = up
        else:
            vertical_error_px = image_height / 2 - target.bbox.cy
            if abs(vertical_error_px) < self.limits["vertical_deadband_px"]:
                vertical_error_px = 0.0
            vz = -self._vertical_pid.step(vertical_error_px, dt)
        vz = max(-max_speed, min(max_speed, vz))

        return GuidanceCommand(vx_mps=vx, vy_mps=vy, vz_mps=vz, yaw_rate_rads=yaw_rate)
