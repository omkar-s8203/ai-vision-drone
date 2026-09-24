"""The safety pass's tunables live in config, not code: each is required and
range-checked at boot (a typo must stop the service, not silently fall back
to a value nobody chose), their timings fit together with the systemd unit's
WatchdogSec, and each one is actually threaded to the code that uses it."""

import configparser
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from companion.config.loader import load_yaml as real_load_yaml
from companion.main import StartupHealthCheckError, build_hardware_orchestrator, run_startup_health_check

REPO_ROOT = Path(__file__).resolve().parents[2]

# (file, key path, a value outside the allowed range)
NEW_PARAMETERS = [
    ("safety_limits.yaml", ["target_hold_after_unseen_s"], 30.0),
    ("safety_limits.yaml", ["detection_carry_max_s"], 0.0),
    ("safety_limits.yaml", ["pipeline_max_frame_age_s"], 60.0),
    ("hardware.yaml", ["camera", "stall_timeout_s"], 0.0),
    ("hardware.yaml", ["mavlink", "silence_reconnect_s"], 0.5),
    ("hardware.yaml", ["mavlink", "reconnect_max_delay_s"], 600.0),
    ("network.yaml", ["ws_send_queue_max"], 1),
]


def _configs_with(file_name, path, value=None, remove=False):
    """The real repo configs, with one value replaced or removed."""

    def load(name):
        cfg = real_load_yaml(name)
        if name != file_name:
            return cfg
        node = cfg
        for key in path[:-1]:
            node = node[key]
        if remove:
            del node[path[-1]]
        else:
            node[path[-1]] = value
        return cfg

    return load


@pytest.mark.parametrize("file_name,path,_bad", NEW_PARAMETERS)
def test_every_new_parameter_is_present_and_in_range_in_the_repo_config(file_name, path, _bad):
    node = real_load_yaml(file_name)
    for key in path:
        node = node[key]
    assert isinstance(node, (int, float)) and math.isfinite(node)


@pytest.mark.parametrize("file_name,path,_bad", NEW_PARAMETERS)
def test_a_missing_parameter_stops_boot(file_name, path, _bad):
    with patch("companion.main.load_yaml", side_effect=_configs_with(file_name, path, remove=True)):
        with pytest.raises(StartupHealthCheckError, match=f"missing required key '{'.'.join(path)}'"):
            run_startup_health_check("hardware")


@pytest.mark.parametrize("file_name,path,bad", NEW_PARAMETERS)
def test_an_out_of_range_parameter_stops_boot(file_name, path, bad):
    with patch("companion.main.load_yaml", side_effect=_configs_with(file_name, path, bad)):
        with pytest.raises(StartupHealthCheckError, match=f"{'.'.join(path)}={bad!r} must be a number"):
            run_startup_health_check("hardware")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "0.3", None])
def test_a_non_numeric_hold_time_stops_boot(bad):
    loader = _configs_with("safety_limits.yaml", ["target_hold_after_unseen_s"], bad)
    with patch("companion.main.load_yaml", side_effect=loader):
        with pytest.raises(StartupHealthCheckError, match="target_hold_after_unseen_s"):
            run_startup_health_check("sim")


def test_the_camera_stall_must_come_before_the_watchdog_frame_age():
    loader = _configs_with("hardware.yaml", ["camera", "stall_timeout_s"], 6.0)
    with patch("companion.main.load_yaml", side_effect=loader):
        with pytest.raises(StartupHealthCheckError, match="must be shorter than"):
            run_startup_health_check("hardware")


def test_sim_mode_does_not_need_the_hardware_only_parameters():
    loader = _configs_with("hardware.yaml", ["camera", "stall_timeout_s"], remove=True)
    with patch("companion.main.load_yaml", side_effect=loader):
        run_startup_health_check("sim")  # must not raise


# --- the timings fit together --------------------------------------------------

def _unit():
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # keep systemd's CamelCase keys
    parser.read(REPO_ROOT / "deploy" / "ai-vision-drone.service", encoding="utf-8")
    return parser


def test_the_unit_is_a_watchdog_supervised_always_restarting_notify_service():
    unit = _unit()
    service = unit["Service"]
    assert service["Type"] == "notify"
    assert service["NotifyAccess"] == "main"
    assert service["Restart"] == "always"
    assert float(service["WatchdogSec"]) > 0
    assert unit["Unit"]["StartLimitIntervalSec"] == "0"  # never gives up restarting


def test_camera_stall_then_pipeline_age_then_watchdog_sec():
    """The camera's own clean exit comes first, then the watchdog pings stop,
    all inside the unit's WatchdogSec."""
    stall_s = real_load_yaml("hardware.yaml")["camera"]["stall_timeout_s"]
    frame_age_s = real_load_yaml("safety_limits.yaml")["pipeline_max_frame_age_s"]
    watchdog_sec = float(_unit()["Service"]["WatchdogSec"])
    assert stall_s < frame_age_s < watchdog_sec


def test_mavlink_is_only_reopened_after_guidance_has_already_stopped():
    """The 2s HeartbeatWatchdog window has stopped guidance well before a
    silent link is torn down and reopened."""
    silence_s = real_load_yaml("hardware.yaml")["mavlink"]["silence_reconnect_s"]
    assert silence_s > 2.0


def test_the_hold_comes_before_the_carried_detections_run_out_and_the_target_is_lost():
    safety = real_load_yaml("safety_limits.yaml")
    assert safety["target_hold_after_unseen_s"] <= safety["detection_carry_max_s"]


# --- each value reaches the code that uses it ----------------------------------

def test_build_hardware_orchestrator_threads_every_parameter_through():
    hardware = real_load_yaml("hardware.yaml")
    network = real_load_yaml("network.yaml")
    with patch("companion.vision.camera.Picamera2IMX500Camera") as camera_cls, \
         patch("companion.vision.detector.IMX500Detector"), \
         patch("companion.comms.video_pipeline.AiortcVideoPipeline"), \
         patch("companion.main.MavlinkBridge") as bridge_cls, \
         patch("companion.main.WebSocketTransport") as transport_cls, \
         patch("companion.main.SessionRecorder"), \
         patch("companion.main.VideoRecorder"), \
         patch("companion.main.CompanionOrchestrator"):
        camera_cls.return_value.imx500.network_intrinsics.labels = ["person"]
        build_hardware_orchestrator()

    assert camera_cls.call_args.kwargs["stall_timeout_s"] == hardware["camera"]["stall_timeout_s"]
    assert bridge_cls.call_args.kwargs["silence_reconnect_s"] == hardware["mavlink"]["silence_reconnect_s"]
    assert bridge_cls.call_args.kwargs["reconnect_max_delay_s"] == hardware["mavlink"]["reconnect_max_delay_s"]
    assert transport_cls.call_args.kwargs["send_queue_max"] == network["ws_send_queue_max"]


def test_the_orchestrator_reads_the_flicker_parameters(tmp_path):
    from companion.tests.test_tracking_safety_orchestrator import _build

    safety = real_load_yaml("safety_limits.yaml")
    with _build(tmp_path) as (orch, _rec, _conn):
        assert orch.target_hold_after_unseen_s == safety["target_hold_after_unseen_s"]
        assert orch.detection_carry_max_s == safety["detection_carry_max_s"]


@pytest.mark.asyncio
async def test_amain_gives_the_service_watchdog_the_configured_frame_age():
    from unittest.mock import AsyncMock

    from companion.main import _amain

    orchestrator = MagicMock()
    orchestrator.start = AsyncMock()
    mock_fc = MagicMock()
    mock_fc.run = AsyncMock()
    with patch("companion.main.configure_logging"), \
         patch("companion.main.run_startup_health_check"), \
         patch("companion.main.build_sim_orchestrator", return_value=(orchestrator, mock_fc)), \
         patch("companion.main.SystemdWatchdog") as watchdog_cls:
        watchdog_cls.return_value.run = AsyncMock()
        await _amain()
        is_healthy = watchdog_cls.call_args.kwargs["is_healthy"]
        is_healthy()
    expected = real_load_yaml("safety_limits.yaml")["pipeline_max_frame_age_s"]
    orchestrator.pipeline_healthy.assert_called_once_with(expected)
