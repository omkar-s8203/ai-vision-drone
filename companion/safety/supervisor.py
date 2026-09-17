from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from companion.safety.proximity_guard import ObstacleAlert
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tracking.state import TrackingState

REQUIRED_SUBSYSTEMS = ["camera", "tracker", "mavlink", "comms"]


class SupervisorState(Enum):
    IDLE = auto()
    TRACKING = auto()
    FOLLOWING = auto()
    ORBITING = auto()
    APPROACHING = auto()
    SMART_SHOT = auto()  # one-shot cinematic move (Dronie/Parabola) - see smart_shot.py
    SAFE = auto()  # fault or pilot override in effect - guidance disabled


@dataclass
class SupervisorInputs:
    fc_mode: Optional[str]
    ai_guidance_mode_name: str
    rc_override_active: bool
    tracking_state: TrackingState
    comms_alive: bool
    requested_state: SupervisorState
    obstacle_alert: Optional[ObstacleAlert] = None


@dataclass
class SupervisorDecision:
    state: SupervisorState
    guidance_allowed: bool
    reason: Optional[str]


class SafetySupervisor:
    """Single authority gating whether any guidance command may reach
    MAVLink. Every guidance path (Follow, Orbit, Approach-Test) must have
    its output checked against `evaluate()` before it is sent - see docs
    plan M10 and docs/safety-case.md. Also applies a cross-mode obstacle
    proximity check (companion/safety/proximity_guard.py) independent of
    whichever guidance controller is active.
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

        if inputs.obstacle_alert is not None:
            self.state = SupervisorState.SAFE
            alert = inputs.obstacle_alert
            return SupervisorDecision(
                self.state, False, f"obstacle_too_close:{alert.class_name}:{alert.distance_m:.1f}m"
            )

        if not inputs.comms_alive:
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "comms_lost")

        if inputs.fc_mode != inputs.ai_guidance_mode_name:
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "fc_not_in_ai_mode")

        if inputs.tracking_state == TrackingState.TARGET_LOST and inputs.requested_state in (
            SupervisorState.FOLLOWING,
            SupervisorState.ORBITING,
            SupervisorState.APPROACHING,
            SupervisorState.SMART_SHOT,
        ):
            self.state = SupervisorState.SAFE
            return SupervisorDecision(self.state, False, "target_lost")

        self.state = inputs.requested_state
        allowed = self.state in (
            SupervisorState.FOLLOWING,
            SupervisorState.ORBITING,
            SupervisorState.APPROACHING,
            SupervisorState.SMART_SHOT,
        )
        return SupervisorDecision(self.state, allowed, None)
