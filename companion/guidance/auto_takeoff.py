from __future__ import annotations

from enum import Enum, auto
from typing import Optional


class AutoTakeoffPhase(Enum):
    IDLE = auto()
    WAITING_TO_ARM = auto()
    CLIMBING = auto()
    DONE = auto()
    TIMED_OUT = auto()


class AutoTakeoffController:
    """Sequences "gain height, then start guidance" for a mode freshly
    engaged from the ground (the app's "Arm & Follow" quick action) - a
    field-reported gap: arming and immediately engaging Follow tried to fly
    horizontally toward the target while still on the ground.

    `MAV_CMD_NAV_TAKEOFF` is a one-shot, FC-native command - once accepted
    in GUIDED mode, ArduCopter climbs to the target altitude autonomously
    using its own internal controller. This class never computes a
    velocity command itself; it only sequences WHEN to send that one
    command and WHEN it's safe to let the real guidance controller
    (Follow/Orbit/Approach) start computing setpoints. While
    `is_active`, the caller must withhold real guidance setpoints (send
    nothing) regardless of what the Safety Supervisor would otherwise
    allow - ArduCopter is already climbing on its own and needs no
    setpoints from this companion during that climb; sending Follow's
    normal horizontal-approach setpoints mid-climb is exactly the bug
    this exists to prevent.
    """

    def __init__(self, limits: dict) -> None:
        self.limits = limits
        self.phase = AutoTakeoffPhase.IDLE
        self.target_altitude_m: Optional[float] = None
        self._elapsed_s = 0.0

    @property
    def is_active(self) -> bool:
        return self.phase in (AutoTakeoffPhase.WAITING_TO_ARM, AutoTakeoffPhase.CLIMBING)

    def start(self, target_altitude_m: Optional[float] = None) -> None:
        self.target_altitude_m = (
            target_altitude_m if target_altitude_m is not None else self.limits["altitude_m"]
        )
        self.phase = AutoTakeoffPhase.WAITING_TO_ARM
        self._elapsed_s = 0.0

    def reset(self) -> None:
        self.phase = AutoTakeoffPhase.IDLE
        self.target_altitude_m = None
        self._elapsed_s = 0.0

    def update(
        self,
        armed: bool,
        fc_mode: Optional[str],
        current_alt_m: Optional[float],
        dt: float,
    ) -> str:
        """Advances phase, returns the action the caller should take this
        frame: "none" (not sequencing anything), "send_takeoff" (call
        MavlinkBridge.takeoff() once, then hold), "hold" (still
        waiting/climbing - send no guidance setpoint this frame), "ready"
        (altitude reached - real guidance may compute setpoints normally
        starting this frame), or "timed_out" (gave up waiting - caller
        should abort back to idle rather than silently holding forever)."""
        if self.phase in (AutoTakeoffPhase.IDLE, AutoTakeoffPhase.DONE, AutoTakeoffPhase.TIMED_OUT):
            return "none"

        self._elapsed_s += dt
        if self._elapsed_s >= self.limits.get("timeout_s", 30.0):
            self.phase = AutoTakeoffPhase.TIMED_OUT
            return "timed_out"

        if self.phase == AutoTakeoffPhase.WAITING_TO_ARM:
            if armed and fc_mode == "GUIDED":
                self.phase = AutoTakeoffPhase.CLIMBING
                return "send_takeoff"
            return "hold"

        # CLIMBING
        tolerance_m = self.limits.get("altitude_tolerance_m", 1.0)
        if current_alt_m is not None and self.target_altitude_m is not None:
            if current_alt_m >= self.target_altitude_m - tolerance_m:
                self.phase = AutoTakeoffPhase.DONE
                return "ready"
        return "hold"
