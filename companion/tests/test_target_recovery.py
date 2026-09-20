from companion.config.loader import load_yaml
from companion.guidance.target_recovery import RecoveryPhase, TargetRecoveryController

LIMITS = load_yaml("target_recovery.yaml")


def make_controller(**overrides) -> TargetRecoveryController:
    limits = dict(LIMITS)
    limits.update(overrides)
    return TargetRecoveryController(limits)


def test_idle_when_never_started():
    controller = make_controller()
    result = controller.update(
        now=0.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.IDLE
    assert result.command is None
    assert controller.is_active is False


def test_search_produces_a_nonzero_yaw_sweep_command():
    controller = make_controller(search_timeout_s=60.0)
    controller.start_search(now=0.0)
    result = controller.update(
        now=1.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.SEARCHING
    assert result.command is not None
    assert result.command.vx_mps == 0.0
    assert result.command.vy_mps == 0.0
    assert result.command.vz_mps == 0.0
    assert result.command.yaw_rate_rads != 0.0


def test_sweep_direction_flips_after_half_period():
    controller = make_controller(search_timeout_s=60.0, sweep_half_period_s=4.0)
    controller.start_search(now=0.0)
    first = controller.update(
        now=1.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    after_flip = controller.update(
        now=5.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    assert first.command.yaw_rate_rads > 0
    assert after_flip.command.yaw_rate_rads < 0
    assert abs(after_flip.command.yaw_rate_rads) == abs(first.command.yaw_rate_rads)


def test_start_search_is_idempotent_while_already_searching():
    """Calling start_search again mid-search must not reset the timer -
    the orchestrator calls it every frame the target stays lost."""
    controller = make_controller(search_timeout_s=10.0)
    controller.start_search(now=0.0)
    controller.start_search(now=5.0)  # should be a no-op
    result = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    # If start_search(now=5.0) had reset the clock, we'd still be at
    # elapsed=5s here (< timeout) and get SEARCHING, not a timeout decision.
    assert result.phase != RecoveryPhase.SEARCHING


def test_reacquiring_target_during_search_returns_found_and_cancels():
    controller = make_controller(search_timeout_s=60.0)
    controller.start_search(now=0.0)
    result = controller.update(
        now=2.0, target_reacquired=True, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.FOUND
    assert controller.is_active is False


def test_search_timeout_with_good_battery_triggers_rtl():
    controller = make_controller(search_timeout_s=10.0, low_battery_pct_threshold=20)
    controller.start_search(now=0.0)
    result = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=500.0,
        battery_remaining_pct=80, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.RTL_TRIGGERED
    assert controller.is_active is False


def test_search_timeout_missing_telemetry_defaults_to_rtl():
    """No GPS fix / no home position / no battery reading - ArduPilot's own
    RTL failsafe is a better fallback than guessing at a landing decision
    with incomplete information."""
    controller = make_controller(search_timeout_s=10.0)
    controller.start_search(now=0.0)
    result = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.RTL_TRIGGERED


def test_search_timeout_with_low_battery_and_far_distance_requests_landing():
    controller = make_controller(
        search_timeout_s=10.0,
        low_battery_pct_threshold=20,
        assumed_return_speed_mps=5.0,
        assumed_max_flight_time_s=900,
        rtl_safety_margin=1.5,
    )
    controller.start_search(now=0.0)
    # 10% battery -> 90s estimated remaining flight time.
    # 5000m at 5 m/s -> 1000s estimated return time, times 1.5 margin = 1500s.
    # 90s << 1500s -> not enough to safely RTL -> land.
    result = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=5000.0,
        battery_remaining_pct=10, obstacle_detected=True, obstacle_class_name="car",
    )
    assert result.phase == RecoveryPhase.LAND_CONFIRMATION_REQUESTED
    assert result.obstacle_detected is True
    assert result.obstacle_class_name == "car"
    assert controller.is_active is True  # now awaiting operator confirmation


def test_search_timeout_with_low_battery_but_close_distance_still_triggers_rtl():
    controller = make_controller(
        search_timeout_s=10.0,
        low_battery_pct_threshold=20,
        assumed_return_speed_mps=5.0,
        assumed_max_flight_time_s=900,
        rtl_safety_margin=1.5,
    )
    controller.start_search(now=0.0)
    # 15% battery -> 135s estimated remaining flight time.
    # 10m at 5 m/s -> 2s estimated return time, times 1.5 margin = 3s.
    # 135s >> 3s -> plenty of time to RTL.
    result = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=10.0,
        battery_remaining_pct=15, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.RTL_TRIGGERED


def test_awaiting_confirmation_persists_without_resending_the_request():
    controller = make_controller(search_timeout_s=10.0, low_battery_pct_threshold=20)
    controller.start_search(now=0.0)
    first = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=5000.0,
        battery_remaining_pct=5, obstacle_detected=False,
    )
    second = controller.update(
        now=10.1, target_reacquired=False, distance_to_home_m=5000.0,
        battery_remaining_pct=5, obstacle_detected=False,
    )
    assert first.phase == RecoveryPhase.LAND_CONFIRMATION_REQUESTED
    assert second.phase == RecoveryPhase.AWAITING_LAND_CONFIRMATION


def test_confirm_landing_clears_the_wait_state():
    controller = make_controller(search_timeout_s=10.0, low_battery_pct_threshold=20)
    controller.start_search(now=0.0)
    controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=5000.0,
        battery_remaining_pct=5, obstacle_detected=False,
    )
    assert controller.is_active is True

    controller.confirm_landing(approved=True)

    assert controller.is_active is False
    result = controller.update(
        now=10.2, target_reacquired=False, distance_to_home_m=5000.0,
        battery_remaining_pct=5, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.IDLE


def test_cancel_resets_a_search_in_progress():
    controller = make_controller(search_timeout_s=60.0)
    controller.start_search(now=0.0)
    controller.cancel()
    assert controller.is_active is False
    result = controller.update(
        now=1.0, target_reacquired=False, distance_to_home_m=None,
        battery_remaining_pct=None, obstacle_detected=False,
    )
    assert result.phase == RecoveryPhase.IDLE


def test_reacquiring_target_while_awaiting_land_confirmation_resumes_follow():
    """A real bug found in a code-review audit: the reacquire-cancel check
    was gated on `_searching_since is not None`, which the timeout branch
    already clears the moment it decides to ask for a land confirmation -
    before `_awaiting_confirmation` is even set. A target reacquired while
    that request was outstanding was silently ignored, leaving the
    controller stuck waiting on the operator forever instead of resuming
    Follow/Orbit on the now-visible target."""
    controller = make_controller(search_timeout_s=10.0, low_battery_pct_threshold=20)
    controller.start_search(now=0.0)
    requested = controller.update(
        now=10.0, target_reacquired=False, distance_to_home_m=5000.0,
        battery_remaining_pct=5, obstacle_detected=False,
    )
    assert requested.phase == RecoveryPhase.LAND_CONFIRMATION_REQUESTED
    assert controller.is_active is True

    result = controller.update(
        now=12.0, target_reacquired=True, distance_to_home_m=5000.0,
        battery_remaining_pct=5, obstacle_detected=False,
    )

    assert result.phase == RecoveryPhase.FOUND
    assert controller.is_active is False
