"""Tests for main.py's boot-time health self-check (docs plan M15) - a real
gap found in a code-review audit: a missing/misspelled config key used to
surface as a bare KeyError several stack frames into camera/MAVLink
construction, with no indication of which file or field was actually
wrong. run_startup_health_check() catches that class of problem up front,
before any hardware is touched."""

from unittest.mock import patch

import pytest

from companion.main import StartupHealthCheckError, _amain, run_startup_health_check

_COMPLETE_GRID_SEARCH_CONFIG = {
    "leg_spacing_m": 15.0,
    "min_dimension_m": 20.0,
    "max_dimension_m": 200.0,
    "search_speed_mps": 2.5,
    "waypoint_radius_m": 3.0,
    "max_heading_error_deg_to_advance": 25.0,
    "max_yaw_rate_rads": 0.5,
    "max_speed_mps": 2.5,
    "pid": {"yaw": {"kp": 0.02, "ki": 0.0, "kd": 0.005}, "altitude": {"kp": 0.5, "ki": 0.05, "kd": 0.1}},
}

_COMPLETE_FOLLOW_CONFIG = {
    "max_accel_mps2": 1.5, "min_altitude_m": 2.0, "max_altitude_m": 30.0,
    "min_separation_m": 3.0, "max_separation_m": 15.0, "target_separation_m": 6.0,
}
_COMPLETE_ORBIT_CONFIG = {
    "max_accel_mps2": 1.5, "min_altitude_m": 2.0, "max_altitude_m": 30.0,
    "min_radius_m": 3.0, "max_radius_m": 20.0, "orbit_radius_m": 8.0,
}

_COMPLETE_SAFETY_CONFIG = {
    "min_obstacle_distance_m": 2.0, "min_battery_pct": 20, "min_takeoff_battery_pct": 30, "min_gps_fix_type": 3,
    "max_force_disarm_altitude_m": 1.5,
}


def test_passes_against_the_real_repo_configs_in_sim_mode():
    """The actual companion/config/*.yaml files checked into this repo must
    satisfy the check today - a false positive here would block every sim
    run."""
    run_startup_health_check("sim")  # must not raise


def test_passes_against_the_real_repo_configs_in_hardware_mode():
    run_startup_health_check("hardware")  # must not raise


def test_sim_mode_does_not_require_mavlink_config():
    """build_sim_orchestrator() never reads hardware.yaml's mavlink section
    (it hardcodes its own loopback UDP ports) - the check must not demand
    it for sim mode."""
    fake_configs = {
        "hardware.yaml": {"camera": {"width": 1280, "height": 720, "target_fps": 30}},
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765, "comms_timeout_s": 3.0, "comms_loss_rtl_s": 15.0},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": _COMPLETE_SAFETY_CONFIG,
        "grid_search_limits.yaml": _COMPLETE_GRID_SEARCH_CONFIG,
        "follow_limits.yaml": _COMPLETE_FOLLOW_CONFIG,
        "orbit_limits.yaml": _COMPLETE_ORBIT_CONFIG,
    }
    with patch("companion.main.load_yaml", side_effect=lambda name: fake_configs.get(name, {})):
        run_startup_health_check("sim")  # must not raise


def test_hardware_mode_requires_mavlink_and_imx500_config():
    fake_configs = {
        "hardware.yaml": {"camera": {"width": 1280, "height": 720, "target_fps": 30}},
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765, "comms_timeout_s": 3.0, "comms_loss_rtl_s": 15.0},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": _COMPLETE_SAFETY_CONFIG,
    }
    with patch("companion.main.load_yaml", side_effect=lambda name: fake_configs.get(name, {})):
        with pytest.raises(StartupHealthCheckError) as exc_info:
            run_startup_health_check("hardware")
    assert "mavlink.connection" in str(exc_info.value)
    assert "mavlink.baud" in str(exc_info.value)
    assert "camera.imx500_model_path" in str(exc_info.value)


def test_reports_every_missing_key_at_once_not_just_the_first():
    with patch("companion.main.load_yaml", return_value={}):
        with pytest.raises(StartupHealthCheckError) as exc_info:
            run_startup_health_check("sim")
    message = str(exc_info.value)
    assert "camera.width" in message
    assert "camera.height" in message
    assert "camera.target_fps" in message
    assert "ws_host" in message
    assert "rc_override_deadband" in message
    assert "min_obstacle_distance_m" in message
    assert "grid_search_limits.yaml" in message


def test_flags_a_missing_grid_search_key_instead_of_only_parse_checking_it():
    """A deep-audit gap: grid_search_limits.yaml used to only be passed
    through the parse-only loop (confirms it's valid YAML, nothing else),
    even though GridSearchController.__init__ unconditionally indexes
    pid.yaw/pid.altitude/max_yaw_rate_rads/max_speed_mps (failing at
    orchestrator construction, right after this check would have reported
    "passed") and start()/compute() unconditionally index leg_spacing_m/
    waypoint_radius_m/max_heading_error_deg_to_advance/search_speed_mps
    (only ever hit once grid search is actually engaged, possibly
    mid-flight - an even worse time to discover a config typo)."""
    fake_configs = {
        "hardware.yaml": {"camera": {"width": 1280, "height": 720, "target_fps": 30}},
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765, "comms_timeout_s": 3.0, "comms_loss_rtl_s": 15.0},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": _COMPLETE_SAFETY_CONFIG,
        # A real-world typo: "waypoint_radius_m" renamed/misspelled, and
        # the whole "pid" section missing.
        "grid_search_limits.yaml": {
            "leg_spacing_m": 15.0,
            "search_speed_mps": 2.5,
            "max_heading_error_deg_to_advance": 25.0,
            "max_yaw_rate_rads": 0.5,
            "max_speed_mps": 2.5,
        },
    }
    with patch("companion.main.load_yaml", side_effect=lambda name: fake_configs.get(name, {})):
        with pytest.raises(StartupHealthCheckError) as exc_info:
            run_startup_health_check("sim")
    message = str(exc_info.value)
    assert "grid_search_limits.yaml: missing required key 'waypoint_radius_m'" in message
    assert "grid_search_limits.yaml: missing required key 'pid.yaw'" in message
    assert "grid_search_limits.yaml: missing required key 'pid.altitude'" in message


def test_reports_a_yaml_parse_failure_clearly():
    def flaky_load(name: str):
        if name == "hardware.yaml":
            raise ValueError("mapping values are not allowed here")
        return {}

    with patch("companion.main.load_yaml", side_effect=flaky_load):
        with pytest.raises(StartupHealthCheckError, match="hardware.yaml: failed to parse"):
            run_startup_health_check("sim")


def test_passes_with_no_problems_does_not_raise():
    fake_configs = {
        "hardware.yaml": {
            "camera": {
                "width": 1280, "height": 720, "target_fps": 30,
                "imx500_model_path": "/usr/share/imx500-models/x.rpk",
            },
            "mavlink": {"connection": "/dev/serial0", "baud": 57600},
        },
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765, "comms_timeout_s": 3.0, "comms_loss_rtl_s": 15.0},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": _COMPLETE_SAFETY_CONFIG,
        "grid_search_limits.yaml": _COMPLETE_GRID_SEARCH_CONFIG,
        "follow_limits.yaml": _COMPLETE_FOLLOW_CONFIG,
        "orbit_limits.yaml": _COMPLETE_ORBIT_CONFIG,
    }
    with patch("companion.main.load_yaml", side_effect=lambda name: fake_configs.get(name, {})):
        run_startup_health_check("hardware")  # must not raise


@pytest.mark.asyncio
async def test_amain_exits_before_touching_hardware_when_health_check_fails():
    """The whole point of running this before build_sim_orchestrator()/
    build_hardware_orchestrator() - a bad config must never get as far as
    opening a real camera or MAVLink connection."""
    with patch("companion.main.configure_logging"), \
         patch("companion.main.run_startup_health_check", side_effect=StartupHealthCheckError("boom")), \
         patch("companion.main.build_sim_orchestrator") as mock_build_sim, \
         patch("companion.main.build_hardware_orchestrator") as mock_build_hw:
        with pytest.raises(SystemExit):
            await _amain()
    mock_build_sim.assert_not_called()
    mock_build_hw.assert_not_called()


@pytest.mark.parametrize("file_name,complete,missing_key", [
    ("follow_limits.yaml", _COMPLETE_FOLLOW_CONFIG, "max_accel_mps2"),
    ("follow_limits.yaml", _COMPLETE_FOLLOW_CONFIG, "min_altitude_m"),
    ("follow_limits.yaml", _COMPLETE_FOLLOW_CONFIG, "max_separation_m"),
    ("orbit_limits.yaml", _COMPLETE_ORBIT_CONFIG, "max_accel_mps2"),
    ("orbit_limits.yaml", _COMPLETE_ORBIT_CONFIG, "max_radius_m"),
    ("orbit_limits.yaml", _COMPLETE_ORBIT_CONFIG, "max_altitude_m"),
])
def test_a_missing_enforced_limit_stops_boot_instead_of_silently_disabling_it(file_name, complete, missing_key):
    """These bounds are enforced by the controllers/orchestrator - a config
    that quietly lacks one would run with no floor/ceiling/accel limit."""
    from companion.config.loader import load_yaml as real_load_yaml

    def fake_load(name):
        cfg = real_load_yaml(name)
        if name == file_name:
            cfg = {k: v for k, v in cfg.items() if k != missing_key}
        return cfg

    with patch("companion.main.load_yaml", side_effect=fake_load):
        with pytest.raises(StartupHealthCheckError, match=missing_key):
            run_startup_health_check("sim")


def test_a_camera_resolution_that_does_not_match_the_calibration_stops_boot():
    """Distances assume boxes are in the calibrated pixel space - a mismatch
    would silently skew Follow's forward/back velocity and the proximity check."""
    from companion.config.loader import load_yaml as real_load_yaml

    def fake_load(name):
        cfg = real_load_yaml(name)
        if name == "hardware.yaml":
            cfg = {**cfg, "camera": {**cfg["camera"], "width": 640, "height": 480}}
        return cfg

    with patch("companion.main.load_yaml", side_effect=fake_load):
        with pytest.raises(StartupHealthCheckError, match="does not match hardware.yaml camera.width"):
            run_startup_health_check("sim")


@pytest.mark.parametrize("file_name,missing_key", [
    ("safety_limits.yaml", "min_battery_pct"),
    ("safety_limits.yaml", "min_gps_fix_type"),
    ("network.yaml", "comms_timeout_s"),
    ("network.yaml", "comms_loss_rtl_s"),
])
def test_a_missing_failsafe_setting_stops_boot(file_name, missing_key):
    from companion.config.loader import load_yaml as real_load_yaml

    def fake_load(name):
        cfg = real_load_yaml(name)
        if name == file_name:
            cfg = {k: v for k, v in cfg.items() if k != missing_key}
        return cfg

    with patch("companion.main.load_yaml", side_effect=fake_load):
        with pytest.raises(StartupHealthCheckError, match=missing_key):
            run_startup_health_check("sim")
