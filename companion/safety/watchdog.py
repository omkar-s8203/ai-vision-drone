from __future__ import annotations

import asyncio
import time


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


class SystemdWatchdog:
    """Process-level watchdog via systemd's sd_notify WATCHDOG=1 protocol.
    A no-op off Linux/outside systemd, so it's always safe to instantiate
    during development.
    """

    def __init__(self, interval_s: float = 5.0) -> None:
        self.interval_s = interval_s
        self._enabled = False
        try:
            import sdnotify  # type: ignore

            self._notifier = sdnotify.SystemdNotifier()
            self._enabled = True
        except ImportError:
            self._notifier = None

    async def run(self) -> None:
        if not self._enabled:
            return
        while True:
            self._notifier.notify("WATCHDOG=1")
            await asyncio.sleep(self.interval_s)
