from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from companion.guidance.command import GuidanceCommand


class ApproachState(Enum):
    IDLE = auto()
    APPROACHING = auto()
    STOPPED_AT_BOUNDARY = auto()
    ABORTED = auto()


@dataclass(frozen=True)
class ApproachInputs:
    distance_m: Optional[float]
    contact_detected: bool
    target_tracked: bool
    comms_alive: bool
    rc_override_active: bool
    geofence_breached: bool


@dataclass(frozen=True)
class ApproachResult:
    state: ApproachState
    command: Optional[GuidanceCommand]
    abort_reason: Optional[str]


class ApproachTestController:
    """Controlled approach/contact test against a designated benign test
    fixture in a controlled environment (never an unrestricted collision
    system). Each abort condition below is independently sufficient to halt
    the approach - see docs plan M9. Once ABORTED or STOPPED_AT_BOUNDARY, the
    controller stays there until explicitly start()'d again.
    """

    def __init__(self, limits: dict) -> None:
        self.limits = limits
        self.state = ApproachState.IDLE

    def start(self) -> None:
        self.state = ApproachState.APPROACHING

    def stop(self) -> None:
        self.state = ApproachState.IDLE

    def update(self, inputs: ApproachInputs) -> ApproachResult:
        if self.state != ApproachState.APPROACHING:
            return ApproachResult(self.state, None, None)

        if not inputs.target_tracked:
            self.state = ApproachState.ABORTED
            return ApproachResult(self.state, None, "target_lost")
        if not inputs.comms_alive:
            self.state = ApproachState.ABORTED
            return ApproachResult(self.state, None, "comms_lost")
        if inputs.rc_override_active:
            self.state = ApproachState.ABORTED
            return ApproachResult(self.state, None, "rc_override")
        if inputs.geofence_breached:
            self.state = ApproachState.ABORTED
            return ApproachResult(self.state, None, "geofence_breach")

        min_boundary = self.limits["min_boundary_m"]
        if inputs.contact_detected or (
            inputs.distance_m is not None and inputs.distance_m <= min_boundary
        ):
            self.state = ApproachState.STOPPED_AT_BOUNDARY
            return ApproachResult(self.state, GuidanceCommand(0.0, 0.0, 0.0, 0.0), None)

        if inputs.distance_m is None:
            self.state = ApproachState.ABORTED
            return ApproachResult(self.state, None, "no_distance_estimate")

        max_speed = self.limits["max_approach_speed_mps"]
        margin = max(0.0, inputs.distance_m - min_boundary)
        vx = min(max_speed, 0.5 * margin)
        return ApproachResult(ApproachState.APPROACHING, GuidanceCommand(vx, 0.0, 0.0, 0.0), None)
