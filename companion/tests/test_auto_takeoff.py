from companion.guidance.auto_takeoff import AutoTakeoffController, AutoTakeoffPhase


LIMITS = {"altitude_m": 10.0, "altitude_tolerance_m": 1.0, "timeout_s": 30.0}


def _controller() -> AutoTakeoffController:
    return AutoTakeoffController(dict(LIMITS))


def test_starts_idle_and_inactive():
    c = _controller()
    assert c.phase == AutoTakeoffPhase.IDLE
    assert not c.is_active


def test_start_uses_config_default_altitude():
    c = _controller()
    c.start()
    assert c.phase == AutoTakeoffPhase.WAITING_TO_ARM
    assert c.target_altitude_m == 10.0
    assert c.is_active


def test_start_with_explicit_altitude_overrides_config_default():
    c = _controller()
    c.start(target_altitude_m=25.0)
    assert c.target_altitude_m == 25.0


def test_update_before_start_is_a_no_op():
    c = _controller()
    action = c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)
    assert action == "none"
    assert c.phase == AutoTakeoffPhase.IDLE


def test_waiting_to_arm_holds_until_armed_and_guided():
    c = _controller()
    c.start()

    assert c.update(armed=False, fc_mode=None, current_alt_m=0.0, dt=0.1) == "hold"
    assert c.phase == AutoTakeoffPhase.WAITING_TO_ARM

    assert c.update(armed=True, fc_mode="LOITER", current_alt_m=0.0, dt=0.1) == "hold"
    assert c.phase == AutoTakeoffPhase.WAITING_TO_ARM

    assert c.update(armed=False, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1) == "hold"
    assert c.phase == AutoTakeoffPhase.WAITING_TO_ARM


def test_armed_and_guided_sends_takeoff_exactly_once_then_climbs():
    c = _controller()
    c.start()

    assert c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1) == "send_takeoff"
    assert c.phase == AutoTakeoffPhase.CLIMBING

    # Still climbing - must not re-send the takeoff command every frame.
    assert c.update(armed=True, fc_mode="GUIDED", current_alt_m=2.0, dt=0.1) == "hold"
    assert c.phase == AutoTakeoffPhase.CLIMBING


def test_reaching_target_altitude_within_tolerance_signals_ready():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)

    # target 10.0, tolerance 1.0 -> 9.0m already counts as reached.
    action = c.update(armed=True, fc_mode="GUIDED", current_alt_m=9.0, dt=0.1)
    assert action == "ready"
    assert c.phase == AutoTakeoffPhase.DONE
    assert not c.is_active


def test_below_tolerance_keeps_holding():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)

    action = c.update(armed=True, fc_mode="GUIDED", current_alt_m=8.9, dt=0.1)
    assert action == "hold"
    assert c.phase == AutoTakeoffPhase.CLIMBING


def test_missing_altitude_telemetry_holds_rather_than_crashing():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)

    action = c.update(armed=True, fc_mode="GUIDED", current_alt_m=None, dt=0.1)
    assert action == "hold"
    assert c.phase == AutoTakeoffPhase.CLIMBING


def test_once_done_further_updates_are_a_no_op():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=9.5, dt=0.1)
    assert c.phase == AutoTakeoffPhase.DONE

    assert c.update(armed=True, fc_mode="GUIDED", current_alt_m=9.5, dt=0.1) == "none"
    assert c.phase == AutoTakeoffPhase.DONE


def test_timeout_while_waiting_to_arm():
    c = _controller()
    c.start()

    c.update(armed=False, fc_mode=None, current_alt_m=0.0, dt=29.0)
    action = c.update(armed=False, fc_mode=None, current_alt_m=0.0, dt=2.0)
    assert action == "timed_out"
    assert c.phase == AutoTakeoffPhase.TIMED_OUT
    assert not c.is_active


def test_timeout_while_climbing_and_never_reaching_altitude():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)

    c.update(armed=True, fc_mode="GUIDED", current_alt_m=3.0, dt=29.0)
    action = c.update(armed=True, fc_mode="GUIDED", current_alt_m=3.0, dt=2.0)
    assert action == "timed_out"
    assert c.phase == AutoTakeoffPhase.TIMED_OUT


def test_once_timed_out_further_updates_are_a_no_op():
    c = _controller()
    c.start()
    c.update(armed=False, fc_mode=None, current_alt_m=0.0, dt=31.0)
    assert c.phase == AutoTakeoffPhase.TIMED_OUT

    assert c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1) == "none"
    assert c.phase == AutoTakeoffPhase.TIMED_OUT


def test_reset_clears_state_from_any_phase():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1)
    assert c.phase == AutoTakeoffPhase.CLIMBING

    c.reset()
    assert c.phase == AutoTakeoffPhase.IDLE
    assert c.target_altitude_m is None
    assert not c.is_active

    # A fresh start after reset behaves like a brand-new sequence.
    c.start()
    assert c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=0.1) == "send_takeoff"


def test_restart_after_done_resets_elapsed_timer():
    c = _controller()
    c.start()
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=0.0, dt=25.0)
    c.update(armed=True, fc_mode="GUIDED", current_alt_m=9.5, dt=0.1)
    assert c.phase == AutoTakeoffPhase.DONE

    c.reset()
    c.start()
    # If the elapsed timer had leaked across restarts, this would already
    # be past the 30s timeout and immediately time out instead of holding.
    assert c.update(armed=False, fc_mode=None, current_alt_m=0.0, dt=0.1) == "hold"
