from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from companion.guidance.command import GuidanceCommand


class RecoveryPhase(Enum):
    IDLE = auto()  # not engaged - normal operation
    SEARCHING = auto()  # actively yaw-sweeping, looking for the target
    FOUND = auto()  # one-shot: target reacquired during the search window
    RTL_TRIGGERED = auto()  # one-shot: search timed out, RTL is the decision
    LAND_CONFIRMATION_REQUESTED = auto()  # one-shot: search timed out, battery/distance say land - ask the operator
    AWAITING_LAND_CONFIRMATION = auto()  # persists every frame after the request, until the operator answers


@dataclass
class RecoveryResult:
    phase: RecoveryPhase
    command: Optional[GuidanceCommand] = None
    distance_to_home_m: Optional[float] = None
    obstacle_detected: bool = False
    obstacle_class_name: Optional[str] = None


class TargetRecoveryController:
    """Runs when a Follow/Orbit target is lost and not reacquired by the
    tracker's own short REACQUIRE window or appearance-based rematch
    (companion/tracking/state.py, companion/tracking/appearance.py): a
    bounded yaw-sweep search, then - if the target still isn't found - a
    decision between RTL and an operator-confirmed landing, based on
    battery and an estimated RTL feasibility.

    Every velocity command this proposes during the search still passes
    through SafetySupervisor.evaluate() like any other guidance controller
    (docs plan M10) - RC override, comms loss, obstacle proximity etc. all
    still apply while searching. RTL and LAND are FC mode changes, not
    velocity setpoints - CompanionOrchestrator triggers them directly via
    MavlinkBridge.set_mode() once this controller decides, the same way
    arm()/set_mode() already bypass the velocity-setpoint gate (see
    main.py's _on_set_flight_mode) - administrative commands, not guidance.

    The RTL-vs-land decision (see _decide_rtl_or_land) rests on assumed
    constants (an assumed RTL cruise speed and an assumed full-battery
    flight time), not a live-measured battery drain rate - measuring a
    real drain rate needs a time series that takes a while to stabilize
    after boot, whereas these constants are usable immediately. They are
    aircraft-specific and MUST be tuned from real flight data
    (target_recovery.yaml) before being trusted - see docs/safety-case.md.
    """

    def __init__(self, limits: dict) -> None:
        self.limits = limits
        self._searching_since: Optional[float] = None
        self._sweep_direction = 1.0
        self._last_direction_flip_ts: Optional[float] = None
        self._awaiting_confirmation = False

    @property
    def is_active(self) -> bool:
        return self._searching_since is not None or self._awaiting_confirmation

    def start_search(self, now: float) -> None:
        """No-op if a search or a pending land confirmation is already in
        progress - call this every frame the target is lost while a
        recovery-eligible mode (Follow/Orbit) is requested; it only takes
        effect once."""
        if self._searching_since is None and not self._awaiting_confirmation:
            self._searching_since = now
            self._last_direction_flip_ts = now
            self._sweep_direction = 1.0

    def cancel(self) -> None:
        """Target reacquired, or the operator/orchestrator otherwise wants
        to abandon recovery entirely (e.g. an explicit abort)."""
        self._searching_since = None
        self._awaiting_confirmation = False
        self._last_direction_flip_ts = None

    def confirm_landing(self, approved: bool) -> None:
        """Call once, when the operator's land_confirmation_response
        arrives. The actual LAND mode change (if approved) is the
        orchestrator's responsibility, using the same `approved` value -
        this just clears the internal wait state either way."""
        self._awaiting_confirmation = False

    def update(
        self,
        now: float,
        target_reacquired: bool,
        distance_to_home_m: Optional[float],
        battery_remaining_pct: Optional[float],
        obstacle_detected: bool,
        obstacle_class_name: Optional[str] = None,
    ) -> RecoveryResult:
        if target_reacquired and self._searching_since is not None:
            self.cancel()
            return RecoveryResult(phase=RecoveryPhase.FOUND)

        if self._awaiting_confirmation:
            return RecoveryResult(
                phase=RecoveryPhase.AWAITING_LAND_CONFIRMATION,
                distance_to_home_m=distance_to_home_m,
                obstacle_detected=obstacle_detected,
                obstacle_class_name=obstacle_class_name,
            )

        if self._searching_since is None:
            return RecoveryResult(phase=RecoveryPhase.IDLE)

        elapsed = now - self._searching_since
        if elapsed >= self.limits["search_timeout_s"]:
            self._searching_since = None
            if self._decide_should_land(distance_to_home_m, battery_remaining_pct):
                self._awaiting_confirmation = True
                return RecoveryResult(
                    phase=RecoveryPhase.LAND_CONFIRMATION_REQUESTED,
                    distance_to_home_m=distance_to_home_m,
                    obstacle_detected=obstacle_detected,
                    obstacle_class_name=obstacle_class_name,
                )
            return RecoveryResult(phase=RecoveryPhase.RTL_TRIGGERED, distance_to_home_m=distance_to_home_m)

        # Still within the search window - sweep yaw back and forth rather
        # than spinning continuously, staying roughly oriented toward where
        # the target was last seen.
        half_period = self.limits["sweep_half_period_s"]
        if now - self._last_direction_flip_ts >= half_period:
            self._sweep_direction *= -1.0
            self._last_direction_flip_ts = now
        yaw_rate = self._sweep_direction * self.limits["search_yaw_rate_rads"]
        return RecoveryResult(
            phase=RecoveryPhase.SEARCHING,
            command=GuidanceCommand(vx_mps=0.0, vy_mps=0.0, vz_mps=0.0, yaw_rate_rads=yaw_rate),
        )

    def _decide_should_land(
        self, distance_to_home_m: Optional[float], battery_remaining_pct: Optional[float]
    ) -> bool:
        """True means "land in place, with operator confirmation" - False
        means RTL. Missing telemetry (no GPS fix / no home position / no
        battery reading) defaults to False: ArduPilot's own RTL failsafe
        logic is a better fallback than guessing at a landing decision with
        incomplete information."""
        if battery_remaining_pct is None or distance_to_home_m is None:
            return False
        if battery_remaining_pct >= self.limits["low_battery_pct_threshold"]:
            return False

        estimated_return_time_s = distance_to_home_m / self.limits["assumed_return_speed_mps"]
        estimated_remaining_flight_time_s = (
            battery_remaining_pct / 100.0
        ) * self.limits["assumed_max_flight_time_s"]
        return estimated_remaining_flight_time_s < estimated_return_time_s * self.limits["rtl_safety_margin"]
