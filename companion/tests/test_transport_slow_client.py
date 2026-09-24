"""WebSocketTransport must never let one slow phone stall the Pi. broadcast()
used to await every client's send(), which waits for the socket to drain -
a weak WiFi link held up the perception loop, and with it every guidance
setpoint, telemetry update and failsafe check."""

import asyncio

import pytest

from companion.comms.transport import SLOW_CLIENT_CLOSE_CODE, WebSocketTransport


class _FakeSocket:
    """Stands in for a websockets connection. `stalled` makes send() block like
    a full TCP window; incoming messages are fed with `deliver()`."""

    def __init__(self, stalled: bool = False) -> None:
        self.stalled = stalled
        self.sent: list[str] = []
        self.close_code = None
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._unstall = asyncio.Event()
        self.remote_address = ("10.0.0.2", 5555)

    async def send(self, raw: str) -> None:
        if self.stalled:
            await self._unstall.wait()
        self.sent.append(raw)

    def unstall(self) -> None:
        self.stalled = False
        self._unstall.set()

    def deliver(self, raw: str) -> None:
        self._incoming.put_nowait(raw)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_code = code
        self._incoming.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self._incoming.get()
        if raw is None:
            raise StopAsyncIteration
        return raw


async def _connect(transport, ws):
    task = asyncio.create_task(transport._handle_client(ws))
    await asyncio.sleep(0)  # let _handle_client register the client
    assert ws in transport._clients
    return task


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_broadcast_returns_immediately_even_when_a_client_is_stalled():
    transport = WebSocketTransport("127.0.0.1", 0)
    slow = _FakeSocket(stalled=True)
    handler = await _connect(transport, slow)
    for i in range(20):
        await asyncio.wait_for(transport.broadcast(f"m{i}"), timeout=0.05)
    assert slow.sent == []
    slow.unstall()
    await _settle()
    assert slow.sent == [f"m{i}" for i in range(20)]
    await slow.close()
    await handler


@pytest.mark.asyncio
async def test_messages_reach_a_healthy_client_in_order():
    transport = WebSocketTransport("127.0.0.1", 0)
    ws = _FakeSocket()
    handler = await _connect(transport, ws)
    for i in range(5):
        await transport.broadcast(f"m{i}")
    await _settle()
    assert ws.sent == ["m0", "m1", "m2", "m3", "m4"]
    await ws.close()
    await handler


@pytest.mark.asyncio
async def test_a_client_a_whole_queue_behind_is_disconnected():
    transport = WebSocketTransport("127.0.0.1", 0, send_queue_max=5)
    slow = _FakeSocket(stalled=True)
    handler = await _connect(transport, slow)
    for i in range(7):  # 1 taken by the stalled writer + 5 queued + 1 overflow
        await transport.broadcast(f"m{i}")
    await _settle()
    assert slow not in transport._clients
    assert slow.close_code == SLOW_CLIENT_CLOSE_CODE
    assert transport.slow_client_disconnects == 1
    await asyncio.wait_for(handler, timeout=1.0)


@pytest.mark.asyncio
async def test_a_slow_client_does_not_hold_up_the_others():
    transport = WebSocketTransport("127.0.0.1", 0, send_queue_max=5)
    slow, fast = _FakeSocket(stalled=True), _FakeSocket()
    handlers = [await _connect(transport, slow), await _connect(transport, fast)]
    for i in range(10):
        await transport.broadcast(f"m{i}")
        await _settle()
    assert fast.sent == [f"m{i}" for i in range(10)]
    assert fast in transport._clients
    assert slow not in transport._clients
    await fast.close()
    await asyncio.wait_for(asyncio.gather(*handlers), timeout=1.0)


@pytest.mark.asyncio
async def test_a_dropped_slow_client_no_longer_counts_as_connected():
    """Guidance keys off has_clients (via GroundStationLink.is_connected): a
    client that cannot keep up is blind to the drone and must not count."""
    transport = WebSocketTransport("127.0.0.1", 0, send_queue_max=1)
    slow = _FakeSocket(stalled=True)
    handler = await _connect(transport, slow)
    assert transport.has_clients
    for i in range(3):
        await transport.broadcast(f"m{i}")
    assert not transport.has_clients
    await asyncio.wait_for(handler, timeout=1.0)


@pytest.mark.asyncio
async def test_incoming_messages_still_reach_the_handlers():
    transport = WebSocketTransport("127.0.0.1", 0)
    received = []
    transport.on_message(received.append)
    ws = _FakeSocket()
    handler = await _connect(transport, ws)
    ws.deliver('{"type": "ping"}')
    await _settle()
    assert received == ['{"type": "ping"}']
    await ws.close()
    await handler
    assert not transport.has_clients


@pytest.mark.asyncio
async def test_a_real_client_still_receives_broadcasts():
    import websockets

    transport = WebSocketTransport("127.0.0.1", 8799)
    await transport.start()
    try:
        async with websockets.connect("ws://127.0.0.1:8799") as client:
            for _ in range(100):
                if transport.has_clients:
                    break
                await asyncio.sleep(0.01)
            await transport.broadcast("hello")
            assert await asyncio.wait_for(client.recv(), timeout=2.0) == "hello"
    finally:
        await transport.stop()
