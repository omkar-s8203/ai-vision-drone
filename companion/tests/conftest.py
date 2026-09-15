from __future__ import annotations

import asyncio
from typing import Callable


class FakeTransport:
    """Test double for companion.comms.transport.Transport - avoids needing
    a real WebSocket client connected for tests that exercise the comms
    layer indirectly (e.g. the full orchestrator integration test)."""

    def __init__(self, connected: bool = True) -> None:
        self.has_clients = connected
        self.sent: list[str] = []
        self._handlers: list[Callable[[str], None]] = []

    def on_message(self, handler: Callable[[str], None]) -> None:
        self._handlers.append(handler)

    def inject(self, raw: str) -> None:
        for handler in self._handlers:
            handler(raw)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def broadcast(self, raw: str) -> None:
        self.sent.append(raw)


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0, interval: float = 0.05) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(interval)
