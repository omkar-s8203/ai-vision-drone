"""Tests for sim/sitl_harness.py's real-ArduPilot-SITL launch harness.

Real SITL needs a Linux build environment (WSL2 on Windows) with
sim_vehicle.py on PATH - not assumed to be present here (or on this
project's own dev machine). Every test mocks subprocess/os/signal/mavutil
so the actual subprocess-launch and process-group-kill logic (which uses
POSIX-only os.getpgid/os.killpg/signal.SIGKILL - never available on
Windows, only ever exercised for real inside WSL2/Linux) is verified
without needing that environment or a real SITL binary.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sim.mock_fc import MockFlightController
from sim.sitl_harness import RealSitlHarness, get_flight_controller_harness


def test_falls_back_to_mock_when_sim_vehicle_not_on_path():
    with patch("sim.sitl_harness.shutil.which", return_value=None):
        harness = get_flight_controller_harness()
    assert isinstance(harness, MockFlightController)


def test_prefers_real_sitl_when_available_on_path():
    with patch("sim.sitl_harness.shutil.which", return_value="/usr/bin/sim_vehicle.py"), \
         patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        harness = get_flight_controller_harness()
    assert isinstance(harness, RealSitlHarness)
    mock_popen.assert_called_once()


def test_prefer_real_sitl_false_keeps_mock_even_when_available():
    """A caller must be able to opt out of real SITL even when it's
    installed - e.g. a fast unit test run that doesn't want the multi-second
    SITL boot cost."""
    with patch("sim.sitl_harness.shutil.which", return_value="/usr/bin/sim_vehicle.py"), \
         patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        harness = get_flight_controller_harness(prefer_real_sitl=False)
    assert isinstance(harness, MockFlightController)
    mock_popen.assert_not_called()


def test_launches_with_the_expected_command_line():
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        RealSitlHarness(
            vehicle="ArduCopter", frame="quad", home="1.0,2.0,3.0,4.0",
            speedup=2, connection="udpin:127.0.0.1:14999",
        )
    args, kwargs = mock_popen.call_args
    argv = args[0]
    assert argv[0] == "sim_vehicle.py"
    assert "-v" in argv and argv[argv.index("-v") + 1] == "ArduCopter"
    assert "-f" in argv and argv[argv.index("-f") + 1] == "quad"
    assert "--no-mavproxy" in argv
    assert "--custom-location=1.0,2.0,3.0,4.0" in argv
    assert "--speedup=2" in argv
    assert "--out=udpin:127.0.0.1:14999" in argv
    assert kwargs["start_new_session"] is True


def test_wait_ready_raises_immediately_if_the_process_already_exited():
    """If sim_vehicle.py crashed on startup (e.g. a missing ArduPilot build),
    waiting for a heartbeat that will never come would just hang for the
    full timeout - failing fast with the exit code is far more useful."""
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = 1
        harness = RealSitlHarness()

    with pytest.raises(RuntimeError, match="exited early"):
        harness.wait_ready()


def test_wait_ready_raises_timeout_error_when_no_heartbeat_arrives():
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        harness = RealSitlHarness()

    mock_conn = MagicMock()
    mock_conn.wait_heartbeat.return_value = None
    with patch("sim.sitl_harness.mavutil.mavlink_connection", return_value=mock_conn):
        with pytest.raises(TimeoutError, match="no heartbeat|sent no heartbeat"):
            harness.wait_ready(timeout_s=0.01)
    mock_conn.close.assert_called_once()


def test_wait_ready_succeeds_once_a_heartbeat_arrives():
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        harness = RealSitlHarness()

    mock_conn = MagicMock()
    mock_conn.wait_heartbeat.return_value = MagicMock()  # a real heartbeat message
    with patch("sim.sitl_harness.mavutil.mavlink_connection", return_value=mock_conn):
        harness.wait_ready(timeout_s=5.0)  # must not raise
    mock_conn.close.assert_called_once()


def test_stop_is_a_noop_if_the_process_already_exited():
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = 0
        harness = RealSitlHarness()

    with patch("sim.sitl_harness.os") as mock_os:
        harness.stop()
    mock_os.killpg.assert_not_called()


def test_stop_kills_the_whole_process_group_with_sigterm():
    """A bare Popen.terminate() only signals the parent - sim_vehicle.py's
    own SITL child process keeps running past that, the real orphaned-
    process problem this method exists to avoid."""
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        harness = RealSitlHarness()

    with patch("sim.sitl_harness.os") as mock_os, patch("sim.sitl_harness.signal") as mock_signal:
        mock_os.getpgid.return_value = 4242
        harness.stop()

    mock_os.killpg.assert_called_once_with(4242, mock_signal.SIGTERM)
    harness._process.wait.assert_called_once()


def test_stop_escalates_to_sigkill_if_sigterm_does_not_finish_in_time():
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        mock_popen.return_value.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=10.0), None]
        harness = RealSitlHarness()

    with patch("sim.sitl_harness.os") as mock_os, patch("sim.sitl_harness.signal") as mock_signal:
        mock_os.getpgid.return_value = 4242
        harness.stop()

    assert mock_os.killpg.call_args_list == [
        ((4242, mock_signal.SIGTERM),),
        ((4242, mock_signal.SIGKILL),),
    ]


def test_stop_does_not_raise_if_the_process_exits_between_poll_and_getpgid():
    """A deep-audit gap: stop() checked poll() first, then called
    os.getpgid()/os.killpg() a few lines later with no guard - if the real
    sim_vehicle.py process exits in that exact window (e.g. it crashes
    right as stop()/__exit__ runs), getpgid() raises ProcessLookupError,
    which used to propagate straight out of stop() instead of treating
    "already gone" as success, exactly what this method is trying to
    achieve in the first place."""
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        harness = RealSitlHarness()

    with patch("sim.sitl_harness.os") as mock_os:
        mock_os.getpgid.side_effect = ProcessLookupError()
        harness.stop()  # must not raise

    mock_os.killpg.assert_not_called()


def test_stop_does_not_raise_if_the_process_exits_between_sigterm_and_sigkill():
    with patch("sim.sitl_harness.subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        mock_popen.return_value.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=10.0)
        harness = RealSitlHarness()

    with patch("sim.sitl_harness.os") as mock_os, patch("sim.sitl_harness.signal") as mock_signal:
        mock_os.getpgid.return_value = 4242
        mock_os.killpg.side_effect = [None, ProcessLookupError()]
        harness.stop()  # must not raise

    assert mock_os.killpg.call_args_list == [
        ((4242, mock_signal.SIGTERM),),
        ((4242, mock_signal.SIGKILL),),
    ]


def test_context_manager_stops_the_harness_on_exit():
    with patch("sim.sitl_harness.subprocess.Popen"):
        harness = RealSitlHarness()

    with patch.object(harness, "stop") as mock_stop:
        with harness as ctx:
            assert ctx is harness
        mock_stop.assert_called_once()
