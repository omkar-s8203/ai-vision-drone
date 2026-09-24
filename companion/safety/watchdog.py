from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)


class HeartbeatWatchdog:
    """Tracks a last-seen timestamp per named subsystem (camera, tracker,
    mavlink, comms, ...). A stale heartbeat is fed into the Safety
    Supervisor to force GUIDANCE_ALLOWED false - see docs plan M10.
    """

    def __init__(self, timeout_s: float = 1.0, clock=time.monotonic) -> None:
        self.timeout_s = timeout_s
        self._clock = clock
        self._last_seen: dict[str, float] = {}

    def beat(self, name: str) -> None:
        self._last_seen[name] = self._clock()

    def is_stale(self, name: str) -> bool:
        last = self._last_seen.get(name)
        if last is None:
            return True
        return (self._clock() - last) > self.timeout_s

    def stale_subsystems(self, names: list[str]) -> list[str]:
        return [n for n in names if self.is_stale(n)]


def sd_notify(message: str) -> bool:
    """Sends one sd_notify(3) message ("READY=1", "WATCHDOG=1", ...) to the
    socket systemd names in $NOTIFY_SOCKET. False - and nothing sent - when
    not running under systemd (dev machines, tests, Windows). Implemented
    here rather than via the `sdnotify` package: that package was never a
    dependency, so on the Pi the watchdog silently did nothing."""
    address = os.environ.get("NOTIFY_SOCKET")
    family = getattr(socket, "AF_UNIX", None)
    if not address or family is None:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]  # abstract-namespace socket
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
        return True
    except OSError:
        log.warning("sd_notify(%r) to %s failed", message, address, exc_info=True)
        return False


def watchdog_interval_from_env(default_s: float = 5.0) -> float:
    """Half of the unit's WatchdogSec (systemd passes it as $WATCHDOG_USEC),
    as sd_watchdog_enabled(3) recommends; `default_s` when not set."""
    try:
        usec = int(os.environ.get("WATCHDOG_USEC", ""))
    except ValueError:
        return default_s
    return usec / 1e6 / 2 if usec > 0 else default_s


class SystemdWatchdog:
    """Process-level watchdog for deploy/ai-vision-drone.service (Type=notify,
    WatchdogSec). Sends READY=1 once `is_healthy()` first holds - the first
    frame made it through the pipeline - then WATCHDOG=1 every interval, but
    only while `is_healthy()` still holds. A frozen event loop sends nothing
    at all; a perception loop that stopped producing frames stops the pings.
    Either way systemd kills and restarts the service after WatchdogSec, and
    it comes back in IDLE. A no-op outside systemd.
    """

    def __init__(
        self,
        is_healthy: Callable[[], bool] = lambda: True,
        interval_s: Optional[float] = None,
        notify: Callable[[str], bool] = sd_notify,
    ) -> None:
        self.is_healthy = is_healthy
        self.interval_s = interval_s if interval_s is not None else watchdog_interval_from_env()
        self._notify = notify
        self.ready_sent = False

    async def run(self) -> None:
        if self._notify is sd_notify and not os.environ.get("NOTIFY_SOCKET"):
            return  # not under systemd
        unhealthy_logged = False
        while True:
            if self.is_healthy():
                if not self.ready_sent:
                    self.ready_sent = self._notify("READY=1")
                self._notify("WATCHDOG=1")
                unhealthy_logged = False
            elif self.ready_sent and not unhealthy_logged:
                log.error("Perception pipeline stalled - withholding the systemd watchdog ping (restart follows)")
                unhealthy_logged = True
            await asyncio.sleep(self.interval_s)
