"""The systemd service watchdog (deploy/ai-vision-drone.service: Type=notify,
WatchdogSec). It used to depend on the `sdnotify` package, which was never a
dependency, and the unit had no WatchdogSec - so a companion that hung (a
camera stuck in capture, a blocked event loop) was never restarted."""

import asyncio
import os
import socket
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from companion.main import EXIT_CAMERA_STALL, CompanionOrchestrator, _amain
from companion.safety.watchdog import SystemdWatchdog, sd_notify, watchdog_interval_from_env
from companion.vision.camera import CameraBase, CameraStallError, Frame

HAS_UNIX_SOCKETS = hasattr(socket, "AF_UNIX") and os.name == "posix"


# --- sd_notify -----------------------------------------------------------------

def test_sd_notify_is_a_no_op_outside_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sd_notify("READY=1") is False


@pytest.mark.skipif(not HAS_UNIX_SOCKETS, reason="needs AF_UNIX datagram sockets (Linux, like the Pi)")
def test_sd_notify_sends_the_message_to_the_notify_socket(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "notify")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
            server.bind(path)
            monkeypatch.setenv("NOTIFY_SOCKET", path)
            assert sd_notify("WATCHDOG=1") is True
            assert server.recv(64) == b"WATCHDOG=1"


@pytest.mark.skipif(not HAS_UNIX_SOCKETS, reason="needs AF_UNIX datagram sockets (Linux, like the Pi)")
def test_sd_notify_reports_failure_instead_of_raising(monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/nonexistent/notify")
    assert sd_notify("READY=1") is False


@pytest.mark.parametrize("env,expected", [
    ({"WATCHDOG_USEC": "10000000"}, 5.0),  # half of WatchdogSec=10
    ({"WATCHDOG_USEC": "garbage"}, 7.0),
    ({"WATCHDOG_USEC": "0"}, 7.0),
    ({}, 7.0),
])
def test_ping_interval_is_half_the_units_watchdog_sec(monkeypatch, env, expected):
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert watchdog_interval_from_env(default_s=7.0) == expected


# --- SystemdWatchdog -----------------------------------------------------------

async def _run_for(watchdog, seconds):
    task = asyncio.create_task(watchdog.run())
    await asyncio.sleep(seconds)
    task.cancel()


@pytest.mark.asyncio
async def test_nothing_is_sent_until_the_pipeline_is_healthy():
    """READY=1 must wait for the first real frame - with Type=notify, systemd
    restarts a service that never gets there (TimeoutStartSec)."""
    sent = []
    watchdog = SystemdWatchdog(is_healthy=lambda: False, interval_s=0.01, notify=lambda m: sent.append(m) or True)
    await _run_for(watchdog, 0.05)
    assert sent == []


@pytest.mark.asyncio
async def test_ready_is_sent_once_then_watchdog_pings_follow():
    sent = []
    watchdog = SystemdWatchdog(is_healthy=lambda: True, interval_s=0.01, notify=lambda m: sent.append(m) or True)
    await _run_for(watchdog, 0.06)
    assert sent[0] == "READY=1"
    assert sent.count("READY=1") == 1
    assert sent.count("WATCHDOG=1") >= 3


@pytest.mark.asyncio
async def test_pings_stop_while_the_pipeline_is_stalled_and_resume_after():
    sent = []
    healthy = [True]
    watchdog = SystemdWatchdog(is_healthy=lambda: healthy[0], interval_s=0.01, notify=lambda m: sent.append(m) or True)
    task = asyncio.create_task(watchdog.run())
    await asyncio.sleep(0.04)
    healthy[0] = False
    await asyncio.sleep(0.02)  # let an in-flight iteration finish
    pings_when_stalled = sent.count("WATCHDOG=1")
    await asyncio.sleep(0.05)
    assert sent.count("WATCHDOG=1") == pings_when_stalled
    healthy[0] = True
    await asyncio.sleep(0.04)
    task.cancel()
    assert sent.count("WATCHDOG=1") > pings_when_stalled


@pytest.mark.asyncio
async def test_a_failed_ready_is_retried():
    results = iter([False, True, True, True, True, True, True, True, True, True])
    sent = []

    def notify(message):
        sent.append(message)
        return next(results)

    watchdog = SystemdWatchdog(is_healthy=lambda: True, interval_s=0.01, notify=notify)
    await _run_for(watchdog, 0.05)
    assert sent[:3] == ["READY=1", "WATCHDOG=1", "READY=1"]
    assert watchdog.ready_sent


@pytest.mark.asyncio
async def test_the_real_notifier_does_nothing_outside_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    await asyncio.wait_for(SystemdWatchdog(interval_s=0.01).run(), timeout=1.0)  # returns at once


# --- the orchestrator's pipeline health ---------------------------------------

class _ListCamera(CameraBase):
    def __init__(self, n):
        self.n = n

    async def frames(self):
        for i in range(self.n):
            yield Frame(ts=i * 0.033, width=640, height=480, raw_detection_output=[])


def _bare_orchestrator(camera):
    orch = CompanionOrchestrator.__new__(CompanionOrchestrator)
    orch.camera = camera
    orch._last_good_frame_monotonic = None
    return orch


@pytest.mark.asyncio
async def test_the_pipeline_is_unhealthy_before_any_frame():
    assert _bare_orchestrator(_ListCamera(0)).pipeline_healthy(5.0) is False


@pytest.mark.asyncio
async def test_a_processed_frame_makes_the_pipeline_healthy():
    orch = _bare_orchestrator(_ListCamera(2))
    orch.process_frame = AsyncMock()
    await orch._perception_loop()
    assert orch.pipeline_healthy(5.0) is True


@pytest.mark.asyncio
async def test_the_pipeline_goes_unhealthy_when_frames_stop():
    orch = _bare_orchestrator(_ListCamera(1))
    orch.process_frame = AsyncMock()
    await orch._perception_loop()
    orch._last_good_frame_monotonic -= 6.0
    assert orch.pipeline_healthy(5.0) is False


@pytest.mark.asyncio
async def test_frames_that_fail_processing_do_not_count_as_healthy():
    orch = _bare_orchestrator(_ListCamera(3))
    orch.process_frame = AsyncMock(side_effect=RuntimeError("bug"))
    await orch._perception_loop()
    assert orch.pipeline_healthy(5.0) is False


# --- a stalled camera ends the process for systemd to restart -----------------

@pytest.mark.asyncio
async def test_a_camera_stall_exits_with_the_camera_stall_status():
    orchestrator = MagicMock()
    orchestrator.start = AsyncMock(side_effect=CameraStallError("no camera frame for 2.0s"))
    mock_fc = MagicMock()
    mock_fc.run = AsyncMock()
    with patch("companion.main.configure_logging"), \
         patch("companion.main.run_startup_health_check"), \
         patch("companion.main.build_sim_orchestrator", return_value=(orchestrator, mock_fc)):
        with pytest.raises(SystemExit) as excinfo:
            await _amain()
    assert excinfo.value.code == EXIT_CAMERA_STALL
