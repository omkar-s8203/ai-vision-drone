from companion.safety.proximity_guard import ObstacleAlert
from companion.safety.supervisor import REQUIRED_SUBSYSTEMS, SafetySupervisor, SupervisorInputs, SupervisorState
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tracking.state import TrackingState

AI_MODE = "GUIDED"


def fresh_watchdog(timeout_s: float = 5.0) -> HeartbeatWatchdog:
    wd = HeartbeatWatchdog(timeout_s=timeout_s)
    for name in REQUIRED_SUBSYSTEMS:
        wd.beat(name)
    return wd


def base_inputs(**overrides):
    base = dict(
        fc_mode=AI_MODE,
        ai_guidance_mode_name=AI_MODE,
        rc_override_active=False,
        tracking_state=TrackingState.TRACKING,
        comms_alive=True,
        requested_state=SupervisorState.FOLLOWING,
    )
    base.update(overrides)
    return SupervisorInputs(**base)


def test_happy_path_allows_guidance():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(base_inputs())
    assert decision.state == SupervisorState.FOLLOWING
    assert decision.guidance_allowed is True
    assert decision.reason is None


def test_stale_subsystem_forces_safe():
    wd = HeartbeatWatchdog(timeout_s=5.0)
    wd.beat("camera")
    wd.beat("mavlink")
    wd.beat("comms")
    # "tracker" never beaten -> stale
    supervisor = SafetySupervisor(wd)
    decision = supervisor.evaluate(base_inputs())
    assert decision.state == SupervisorState.SAFE
    assert decision.guidance_allowed is False
    assert "tracker" in decision.reason


def test_rc_override_forces_safe():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(base_inputs(rc_override_active=True))
    assert decision.state == SupervisorState.SAFE
    assert decision.reason == "rc_override"


def test_comms_lost_forces_safe():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(base_inputs(comms_alive=False))
    assert decision.reason == "comms_lost"


def test_fc_mode_mismatch_forces_safe():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(base_inputs(fc_mode="STABILIZE"))
    assert decision.reason == "fc_not_in_ai_mode"


def test_target_lost_forces_safe_when_guidance_requested():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(
        base_inputs(tracking_state=TrackingState.TARGET_LOST, requested_state=SupervisorState.FOLLOWING)
    )
    assert decision.reason == "target_lost"


def test_target_lost_does_not_block_plain_tracking_request():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(
        base_inputs(tracking_state=TrackingState.TARGET_LOST, requested_state=SupervisorState.TRACKING)
    )
    assert decision.state == SupervisorState.TRACKING
    assert decision.guidance_allowed is False  # TRACKING never sends guidance anyway


def test_idle_request_never_allows_guidance():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(base_inputs(requested_state=SupervisorState.IDLE))
    assert decision.state == SupervisorState.IDLE
    assert decision.guidance_allowed is False


def test_obstacle_too_close_forces_safe():
    supervisor = SafetySupervisor(fresh_watchdog())
    alert = ObstacleAlert(class_name="wall", distance_m=1.2)
    decision = supervisor.evaluate(base_inputs(obstacle_alert=alert))
    assert decision.state == SupervisorState.SAFE
    assert decision.guidance_allowed is False
    assert decision.reason == "obstacle_too_close:wall:1.2m"


def test_no_obstacle_alert_allows_guidance():
    supervisor = SafetySupervisor(fresh_watchdog())
    decision = supervisor.evaluate(base_inputs(obstacle_alert=None))
    assert decision.guidance_allowed is True


def test_obstacle_alert_takes_priority_over_comms_lost_reason():
    """Order matters for the reported reason (both force SAFE either way) -
    the more physically urgent obstacle warning should be visible in logs/
    telemetry even if comms happens to be down in the same frame."""
    supervisor = SafetySupervisor(fresh_watchdog())
    alert = ObstacleAlert(class_name="person", distance_m=0.8)
    decision = supervisor.evaluate(base_inputs(obstacle_alert=alert, comms_alive=False))
    assert decision.reason == "obstacle_too_close:person:0.8m"
