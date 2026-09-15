from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachInputs, ApproachState, ApproachTestController

LIMITS = load_yaml("approach_limits.yaml")


def good_inputs(**overrides):
    base = dict(
        distance_m=10.0,
        contact_detected=False,
        target_tracked=True,
        comms_alive=True,
        rc_override_active=False,
        geofence_breached=False,
    )
    base.update(overrides)
    return ApproachInputs(**base)


def test_idle_produces_no_command():
    controller = ApproachTestController(LIMITS)
    result = controller.update(good_inputs())
    assert result.state == ApproachState.IDLE
    assert result.command is None


def test_normal_approach_produces_capped_forward_command():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs())
    assert result.state == ApproachState.APPROACHING
    assert result.command is not None
    assert 0 < result.command.vx_mps <= LIMITS["max_approach_speed_mps"]
    assert result.abort_reason is None


def test_target_lost_aborts():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(target_tracked=False))
    assert result.state == ApproachState.ABORTED
    assert result.abort_reason == "target_lost"


def test_comms_lost_aborts():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(comms_alive=False))
    assert result.abort_reason == "comms_lost"


def test_rc_override_aborts():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(rc_override_active=True))
    assert result.abort_reason == "rc_override"


def test_geofence_breach_aborts():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(geofence_breached=True))
    assert result.abort_reason == "geofence_breach"


def test_missing_distance_estimate_aborts():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(distance_m=None))
    assert result.abort_reason == "no_distance_estimate"


def test_reaching_min_boundary_stops_safely():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(distance_m=LIMITS["min_boundary_m"]))
    assert result.state == ApproachState.STOPPED_AT_BOUNDARY
    assert result.command.vx_mps == 0.0
    assert result.abort_reason is None


def test_contact_sensor_stops_regardless_of_distance():
    controller = ApproachTestController(LIMITS)
    controller.start()
    result = controller.update(good_inputs(distance_m=50.0, contact_detected=True))
    assert result.state == ApproachState.STOPPED_AT_BOUNDARY


def test_aborted_state_persists_until_restart():
    controller = ApproachTestController(LIMITS)
    controller.start()
    controller.update(good_inputs(rc_override_active=True))
    assert controller.state == ApproachState.ABORTED

    result = controller.update(good_inputs())
    assert result.state == ApproachState.ABORTED
    assert result.command is None

    controller.start()
    result = controller.update(good_inputs())
    assert result.state == ApproachState.APPROACHING
