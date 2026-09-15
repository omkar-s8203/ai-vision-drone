from __future__ import annotations

import asyncio
from typing import Callable

import websockets

MessageHandler = Callable[[str], None]


class Transport:
    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def broadcast(self, raw: str) -> None:
        raise NotImplementedError

    def on_message(self, handler: MessageHandler) -> None:
        raise NotImplementedError


class WebSocketTransport(Transport):
    """Pi runs as the WebSocket server; the Android app connects as a
    client. Kept behind the Transport interface so WiFi can later be
    swapped for a long-range link without touching callers (docs plan M5).
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._server = None
        self._clients: set = set()
        self._handlers: list[MessageHandler] = []

    def on_message(self, handler: MessageHandler) -> None:
        self._handlers.append(handler)

    async def _handle_client(self, ws) -> None:
        self._clients.add(ws)
        try:
            async for raw in ws:
                for handler in self._handlers:
                    handler(raw)
        finally:
            self._clients.discard(ws)

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_client, self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def broadcast(self, raw: str) -> None:
        if not self._clients:
            return
        await asyncio.gather(
            *(client.send(raw) for client in list(self._clients)), return_exceptions=True
        )

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)
