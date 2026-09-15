from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from companion.safety.watchdog import HeartbeatWatchdog
from companion.tracking.state import TrackingState

REQUIRED_SUBSYSTEMS = ["camera", "tracker", "mavlink", "comms"]


class SupervisorState(Enum):
    IDLE = auto()
    TRACKING = auto()
    FOLLOWING = auto()
    APPROACHING = auto()
    SAFE = auto()  # fault or pilot override in effect - guidance disabled


@dataclass
class SupervisorInputs:
    fc_mode: Optional[str]
    ai_guidance_mode_name: str
    rc_override_active: bool
    tracking_state: TrackingState
    comms_alive: bool
    requested_state: SupervisorState


@dataclass
class SupervisorDecision:
    state: SupervisorState
    guidance_allowed: bool
    reason: Optional[str]


class SafetySupervisor:
    """Single authority gating whether any guidance command may reach
    MAVLink. Every guidance path (Follow, Approach-Test) must have its
    output checked against `evaluate()` before it is sent - see docs plan
    M10 and docs/safety-case.md.
    """

    def __init__(self, watchdog: HeartbeatWatchdog) -> None:
        self.watchdog = watchdog
        self.state = SupervisorState.IDLE

    def evaluate(self, inputs: SupervisorInputs) -> SupervisorDecision:
        stale = self.watchdog.stale_subsystems(REQUIRED_SUBSYSTEMS)
        if stale:
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, f"stale_subsystems:{','.join(stale)}")

        if inputs.rc_override_active:
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "rc_override")

        if not inputs.comms_alive:
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "comms_lost")

        if inputs.fc_mode != inputs.ai_guidance_mode_name:
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "fc_not_in_ai_mode")

        if inputs.tracking_state == TrackingState.TARGET_LOST and inputs.requested_state in (
            SupervisorState.FOLLOWING,
            SupervisorState.APPROACHING,
        ):
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "target_lost")

        self.state = inputs.requested_state
        allowed = self.state in (SupervisorState.FOLLOWING, SupervisorState.APPROACHING)
        return SupervisorDecision(self.state, allowed, None)
