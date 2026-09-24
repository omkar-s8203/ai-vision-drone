from __future__ import annotations

from typing import Optional


class SlewLimiter:
    """Caps how fast a commanded velocity may change (m/s per second), so a
    sudden change in the controller's target - a re-lock, a distance-estimate
    jump, guidance resuming after a pause - never asks the aircraft for an
    instantaneous velocity step. `max_accel_mps2` has been in
    follow_limits.yaml since the plan's M8 ("clamps against max
    speed/acceleration limits") but nothing ever enforced it."""

    def __init__(self, max_accel_mps2: Optional[float]) -> None:
        self.max_accel_mps2 = max_accel_mps2
        self._value = 0.0

    def reset(self) -> None:
        self._value = 0.0

    def override(self, value: float) -> None:
        """Keeps the limiter's own state in step with a later clamp on its
        output, so a value that was refused (e.g. a descent through the
        altitude floor) doesn't linger as a phantom velocity that reappears
        the instant the refusal stops applying."""
        self._value = value

    def step(self, target: float, dt: float) -> float:
        if self.max_accel_mps2 is None:
            self._value = target
            return target
        max_delta = self.max_accel_mps2 * max(0.0, dt)
        delta = target - self._value
        if delta > max_delta:
            delta = max_delta
        elif delta < -max_delta:
            delta = -max_delta
        self._value += delta
        return self._value


def apply_altitude_limits(
    vz: float,
    current_altitude_m: Optional[float],
    min_altitude_m: Optional[float],
    max_altitude_m: Optional[float],
) -> float:
    """MAVLink NED: vz > 0 descends. Never lets a guidance controller push
    the aircraft below `min_altitude_m` or above `max_altitude_m`, whichever
    vertical-control mode is in use - pixel-framing (keep the target centered
    in frame) in particular has no altitude reference of its own, and a
    target below the image center used to command a descent with no floor at
    all. With no altitude telemetry the floor can't be verified, so descent
    is suppressed (climbing is still allowed) rather than assumed safe."""
    if current_altitude_m is None:
        return min(vz, 0.0) if min_altitude_m is not None else vz
    if min_altitude_m is not None and current_altitude_m <= min_altitude_m and vz > 0:
        return 0.0
    if max_altitude_m is not None and current_altitude_m >= max_altitude_m and vz < 0:
        return 0.0
    return vz


def clamp_to_range(value: float, low: Optional[float], high: Optional[float]) -> float:
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value
