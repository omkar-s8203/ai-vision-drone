from __future__ import annotations

import os
import shutil
import signal
import subprocess

from pymavlink import mavutil

from sim.mock_fc import MockFlightController

# ArduPilot's standard CMAC test-flying-field location (lat, lon, alt, heading)
# - the same default sim_vehicle.py itself uses, so behavior matches anyone
# else's SITL session unless a caller overrides it.
DEFAULT_SITL_HOME = "-35.363261,149.165230,584,353"
DEFAULT_SITL_CONNECTION = "udpin:127.0.0.1:14551"
DEFAULT_SITL_READY_TIMEOUT_S = 120.0


class RealSitlHarness:
    """Launches genuine ArduPilot SITL (`sim_vehicle.py`) as a subprocess -
    the real ArduCopter flight-mode/EKF/geofence logic, not an emulation of
    it like MockFlightController. Needs a Linux build environment (WSL2 on
    Windows) with ArduPilot already built and `sim_vehicle.py` on PATH; see
    sim/README.md.

    Exposes `.connection` - a MAVLink endpoint string a MavlinkBridge can
    `connect()` to - the same shape MockFlightController's `bind_address`
    constructor argument implies, so calling code doesn't need to branch on
    which harness it got back (matches this module's own
    get_flight_controller_harness() docstring promise).
    """

    def __init__(
        self,
        vehicle: str = "ArduCopter",
        frame: str = "quad",
        home: str = DEFAULT_SITL_HOME,
        speedup: int = 1,
        connection: str = DEFAULT_SITL_CONNECTION,
    ) -> None:
        self.connection = connection
        # start_new_session=True so the whole process group (sim_vehicle.py
        # spawns the actual SITL binary as a child) can be killed together in
        # stop() - sim_vehicle.py is notorious for leaving orphaned processes
        # behind if only the parent PID is signaled.
        self._process = subprocess.Popen(
            [
                "sim_vehicle.py",
                "-v", vehicle,
                "-f", frame,
                "--no-mavproxy",
                f"--custom-location={home}",
                f"--speedup={speedup}",
                "-A", f"--out={connection}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

    def wait_ready(self, timeout_s: float = DEFAULT_SITL_READY_TIMEOUT_S) -> None:
        """Blocks until SITL is actually emitting MAVLink heartbeats on
        `self.connection`. sim_vehicle.py's own startup (compiling if
        needed, then booting the simulated vehicle and its EKF) can take
        anywhere from several seconds to a couple of minutes - a caller must
        not assume it's ready the instant the subprocess object exists."""
        if self._process.poll() is not None:
            raise RuntimeError(
                f"sim_vehicle.py exited early (code {self._process.returncode}) "
                "before ever becoming ready - check its output for the real error"
            )
        conn = mavutil.mavlink_connection(self.connection)
        try:
            msg = conn.wait_heartbeat(timeout=timeout_s)
        finally:
            conn.close()
        if msg is None:
            raise TimeoutError(
                f"Real SITL sent no heartbeat on {self.connection!r} within "
                f"{timeout_s:.0f}s - check sim_vehicle.py's own console output"
            )

    def stop(self) -> None:
        """Terminates the whole sim_vehicle.py process group. A bare
        Popen.terminate() only signals the parent - its SITL child process
        can and does keep running past that on its own, which is exactly
        the orphaned-process problem start_new_session=True in __init__
        exists to let this method clean up properly."""
        if self._process.poll() is not None:
            return
        pgid = os.getpgid(self._process.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            self._process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)
            self._process.wait(timeout=10.0)

    def __enter__(self) -> "RealSitlHarness":
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()


def get_flight_controller_harness(
    prefer_real_sitl: bool = True,
) -> MockFlightController | RealSitlHarness:
    """Returns a running-FC-like object for integration testing.

    Real ArduPilot SITL needs a Linux build environment (WSL2 on Windows)
    and isn't assumed to be present. MockFlightController is the default so
    the companion MAVLink bridge, RC-override handling, and safety
    supervisor can be exercised without it. When `sim_vehicle.py` is found
    on PATH (and `prefer_real_sitl` is True), launches real SITL instead via
    RealSitlHarness - the companion bridge only needs a MAVLink UDP
    endpoint, so nothing else in the codebase has to change. Callers using
    RealSitlHarness must call `wait_ready()` before connecting a bridge to
    it, and `stop()` (or use it as a context manager) when done.
    """
    if prefer_real_sitl and shutil.which("sim_vehicle.py"):
        return RealSitlHarness()
    return MockFlightController()
