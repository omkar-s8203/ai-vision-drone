from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from companion.guidance.command import GuidanceCommand
from companion.guidance.pid import Pid
from companion.tracking.base import TrackedTarget


class ShotType(Enum):
    DRONIE = auto()  # retreat backward while climbing, camera stays on target
    PARABOLA = auto()  # fly a straight line past the target on a climb-then-descend arc


class SmartShotState(Enum):
    IDLE = auto()
    RUNNING = auto()
    FINISHED = auto()


@dataclass(frozen=True)
class SmartShotResult:
    state: SmartShotState
    command: Optional[GuidanceCommand]


class SmartShotController:
    """One-shot, fixed-duration cinematic camera moves (DJI "QuickShot"
    equivalent) - distinct from Follow/Orbit, which hold a continuous
    relationship to the target indefinitely. A smart shot runs once for
    `duration_s` then stops itself and returns `command=None` from then on
    (mirrors ApproachTestController's STOPPED_AT_BOUNDARY/ABORTED pattern -
    see companion/guidance/approach_test.py) - the orchestrator doesn't need
    to reset its requested mode when a shot completes, it just stops
    receiving commands, and ArduPilot's own GUIDED-mode setpoint-timeout
    behavior holds position once streaming stops (same safety net Follow/
    Orbit/Approach already lean on).

    Camera stays pointed at the target throughout via the same lateral-pixel
    yaw PID Follow/Orbit use - that's what actually sells the shot; the
    body-frame translation (vx/vy/vz) is a simple fixed-speed profile over
    time, not physically exact, consistent with this project's priority
    order (STABLE > LOW LATENCY > ACCURATE).
    """

    def __init__(self, limits: dict) -> None:
        self.limits = limits
        self.state = SmartShotState.IDLE
        self.shot_type: Optional[ShotType] = None
        self._elapsed_s = 0.0
        pid_cfg = limits["pid"]["lateral"]
        self._lateral_pid = Pid(**pid_cfg, out_limit=1.0)  # rad/s

    @property
    def is_active(self) -> bool:
        return self.state == SmartShotState.RUNNING

    def start(self, shot_type: ShotType) -> None:
        self.shot_type = shot_type
        self._elapsed_s = 0.0
        self._lateral_pid.reset()
        self.state = SmartShotState.RUNNING

    def stop(self) -> None:
        self.state = SmartShotState.IDLE
        self.shot_type = None
        self._elapsed_s = 0.0

    def update(
        self, target: Optional[TrackedTarget], image_width: int, image_height: int, dt: float
    ) -> SmartShotResult:
        if self.state != SmartShotState.RUNNING:
            return SmartShotResult(self.state, None)

        self._elapsed_s += dt
        duration = self.limits["duration_s"]
        if self._elapsed_s >= duration:
            self.state = SmartShotState.FINISHED
            self.shot_type = None
            return SmartShotResult(self.state, GuidanceCommand(0.0, 0.0, 0.0, 0.0))

        progress = min(1.0, self._elapsed_s / duration)
        vx, vy, vz = self._profile_velocity(progress)

        yaw_rate = 0.0
        if target is not None:
            lateral_error_px = target.bbox.cx - image_width / 2
            if abs(lateral_error_px) < self.limits["lateral_deadband_px"]:
                lateral_error_px = 0.0
            yaw_rate = self._lateral_pid.step(lateral_error_px, dt)

        return SmartShotResult(self.state, GuidanceCommand(vx, vy, vz, yaw_rate))

    def _profile_velocity(self, progress: float) -> tuple[float, float, float]:
        if self.shot_type == ShotType.DRONIE:
            vx = -self.limits["dronie_retreat_speed_mps"]  # backward, away from target
            vz = -self.limits["dronie_climb_speed_mps"]  # NED: negative = up
            return vx, 0.0, vz
        if self.shot_type == ShotType.PARABOLA:
            vx = self.limits["parabola_speed_mps"]  # constant translation past the target
            # A linearly-decreasing vertical speed (+max climb at the start,
            # 0 at the midpoint, -max at the end) integrates to a genuinely
            # parabolic altitude profile over the shot - climb, level off at
            # the apex, then descend, matching the shot's name literally.
            climb_rate = self.limits["parabola_climb_speed_mps"] * (1.0 - 2.0 * progress)
            vz = -climb_rate  # NED: negative = up
            return vx, 0.0, vz
        return 0.0, 0.0, 0.0
