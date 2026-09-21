"""Tests for main.py's boot-time health self-check (docs plan M15) - a real
gap found in a code-review audit: a missing/misspelled config key used to
surface as a bare KeyError several stack frames into camera/MAVLink
construction, with no indication of which file or field was actually
wrong. run_startup_health_check() catches that class of problem up front,
before any hardware is touched."""

from unittest.mock import patch

import pytest

from companion.main import StartupHealthCheckError, _amain, run_startup_health_check


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
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": {"min_obstacle_distance_m": 2.0},
    }
    with patch("companion.main.load_yaml", side_effect=lambda name: fake_configs.get(name, {})):
        run_startup_health_check("sim")  # must not raise


def test_hardware_mode_requires_mavlink_and_imx500_config():
    fake_configs = {
        "hardware.yaml": {"camera": {"width": 1280, "height": 720, "target_fps": 30}},
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": {"min_obstacle_distance_m": 2.0},
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
        "network.yaml": {"ws_host": "0.0.0.0", "ws_port": 8765},
        "approach_limits.yaml": {"rc_override_deadband": 0.15},
        "safety_limits.yaml": {"min_obstacle_distance_m": 2.0},
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
