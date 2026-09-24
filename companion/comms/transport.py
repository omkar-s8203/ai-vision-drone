from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

import websockets

log = logging.getLogger(__name__)

MessageHandler = Callable[[str], None]

# Per-client outbound backlog, in messages. The Pi sends ~5-6 messages a frame,
# so 200 is roughly one second of updates at 30 FPS. See WebSocketTransport.
DEFAULT_SEND_QUEUE_MAX = 200
# WebSocket close code 1013, "Try Again Later": the app should simply reconnect.
SLOW_CLIENT_CLOSE_CODE = 1013


class Transport:
    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def broadcast(self, raw: str) -> None:
        raise NotImplementedError

    def on_message(self, handler: MessageHandler) -> None:
        raise NotImplementedError


class _ClientChannel:
    """One connected client's outbound queue and the task draining it."""

    def __init__(self, ws, queue_max: int) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_max)
        self.writer: asyncio.Task | None = None


class WebSocketTransport(Transport):
    """Pi runs as the WebSocket server; the Android app connects as a
    client. Kept behind the Transport interface so WiFi can later be
    swapped for a long-range link without touching callers (docs plan M5).

    broadcast() never waits on the network. It used to await every client's
    send() directly, and websockets' send() waits for the socket to drain -
    so one phone on a weak WiFi link held up the perception loop, and with it
    every guidance setpoint, telemetry update and failsafe check, for as long
    as its TCP window stayed full. Now each client has its own bounded queue
    drained by its own writer task. A client that falls a whole queue behind
    (send_queue_max messages, about a second of updates) is disconnected
    rather than fed ever-staler data; the app reconnects and starts fresh.
    """

    def __init__(self, host: str, port: int, send_queue_max: int = DEFAULT_SEND_QUEUE_MAX) -> None:
        self.host = host
        self.port = port
        self.send_queue_max = max(1, int(send_queue_max))
        self._server = None
        self._clients: dict[object, _ClientChannel] = {}
        self._handlers: list[MessageHandler] = []
        # Monotonic time of the last message received from ANY client. A TCP
        # socket can stay "connected" for a long time after the phone has
        # actually gone (WiFi dropped, app frozen) - websockets' own
        # keepalive only notices after tens of seconds - so liveness is
        # judged from real traffic (the app sends a ping every 500ms).
        self._last_rx = time.monotonic()
        self.slow_client_disconnects = 0

    def seconds_since_last_message(self) -> float:
        return time.monotonic() - self._last_rx

    def on_message(self, handler: MessageHandler) -> None:
        self._handlers.append(handler)

    async def _handle_client(self, ws) -> None:
        channel = _ClientChannel(ws, self.send_queue_max)
        channel.writer = asyncio.create_task(self._drain(channel))
        self._clients[ws] = channel
        self._last_rx = time.monotonic()  # a fresh connection starts the clock
        try:
            async for raw in ws:
                self._last_rx = time.monotonic()
                for handler in self._handlers:
                    handler(raw)
        finally:
            self._clients.pop(ws, None)
            channel.writer.cancel()

    async def _drain(self, channel: _ClientChannel) -> None:
        try:
            while True:
                raw = await channel.queue.get()
                await channel.ws.send(raw)
        except asyncio.CancelledError:
            raise
        except websockets.ConnectionClosed:
            pass  # the receive loop in _handle_client sees the close too and cleans up
        except Exception:
            log.exception("Sending to a ground-station client failed - closing it")
            await self._close_quietly(channel.ws, 1011)

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_client, self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def broadcast(self, raw: str) -> None:
        for ws, channel in list(self._clients.items()):
            try:
                channel.queue.put_nowait(raw)
            except asyncio.QueueFull:
                self._drop_slow_client(ws, channel)

    def _drop_slow_client(self, ws, channel: _ClientChannel) -> None:
        if self._clients.pop(ws, None) is None:
            return
        self.slow_client_disconnects += 1
        log.warning(
            "Ground-station client %s is %d messages behind - disconnecting it so it reconnects fresh",
            getattr(ws, "remote_address", "?"), channel.queue.qsize(),
        )
        if channel.writer is not None:
            channel.writer.cancel()
        # Closing waits for the close handshake, which a stalled client may
        # never answer - never on the caller's (the perception loop's) time.
        asyncio.create_task(self._close_quietly(ws, SLOW_CLIENT_CLOSE_CODE))

    @staticmethod
    async def _close_quietly(ws, code: int) -> None:
        try:
            await ws.close(code=code, reason="client too slow" if code == SLOW_CLIENT_CLOSE_CODE else "")
        except Exception:
            log.debug("Closing a ground-station client failed", exc_info=True)

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)
