"""Measures the WebSocket control/telemetry channel's round-trip latency
against docs plan M5's own acceptance metric: WS control round-trip < 50ms.

This is a real network measurement, not a synthetic one - it opens an
actual `websockets` client connection and times real PING -> PONG
round trips against a running GroundStationLink (companion.comms.ws_server),
the same server the Android app talks to. PING/PONG (companion/comms/
protocol.py) are answered directly inside GroundStationLink._dispatch(),
bypassing all app-level handlers/guidance logic, so this measures the
transport's own latency floor - not anything downstream of it.

Usage against the real running companion service (e.g. from a laptop on
the same WiFi as the Pi, which is the actual M5 scenario):

    python tools/ws_latency_benchmark.py --uri ws://<pi-ip>:8765 --count 100

Usage for a local sanity check (no Pi needed - spins up its own
GroundStationLink on localhost and measures against that):

    python tools/ws_latency_benchmark.py --self-test
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets  # noqa: E402

from companion.comms.protocol import Envelope, MessageType, make_envelope  # noqa: E402
from companion.comms.transport import WebSocketTransport  # noqa: E402
from companion.comms.ws_server import GroundStationLink  # noqa: E402

MAX_WS_RTT_MS = 50.0


@dataclass
class WsLatencyResult:
    samples_ms: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.samples_ms)

    @property
    def mean_ms(self) -> float | None:
        return statistics.mean(self.samples_ms) if self.samples_ms else None

    @property
    def p95_ms(self) -> float | None:
        if not self.samples_ms:
            return None
        ordered = sorted(self.samples_ms)
        idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return ordered[idx]

    def p95_ok(self) -> bool:
        return self.p95_ms is not None and self.p95_ms < MAX_WS_RTT_MS

    def passes(self) -> bool:
        return self.count > 0 and self.p95_ok()

    def report(self) -> str:
        if not self.samples_ms:
            return "No round trips completed - nothing to report."
        status = "PASS" if self.p95_ok() else "FAIL"
        return (
            f"WS round trip over {self.count} pings: "
            f"mean {self.mean_ms:.1f}ms, p95 {self.p95_ms:.1f}ms "
            f"(target < {MAX_WS_RTT_MS:.0f}ms) [{status}]"
        )


async def measure_ws_latency(uri: str, count: int = 50, timeout_s: float = 3.0) -> WsLatencyResult:
    result = WsLatencyResult()
    async with websockets.connect(uri) as client:
        for i in range(count):
            sent_at = time.monotonic()
            await client.send(make_envelope(MessageType.PING, {"i": i}, i).to_json())
            deadline = sent_at + timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                raw = await asyncio.wait_for(client.recv(), timeout=remaining)
                envelope = Envelope.from_json(raw)
                if envelope.type == MessageType.PONG and envelope.payload.get("i") == i:
                    result.samples_ms.append((time.monotonic() - sent_at) * 1000.0)
                    break
    return result


async def _run_self_test(count: int) -> WsLatencyResult:
    transport = WebSocketTransport(host="127.0.0.1", port=18790)
    link = GroundStationLink(transport)
    await link.start()
    try:
        return await measure_ws_latency("ws://127.0.0.1:18790", count=count)
    finally:
        await link.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", help="ws://<host>:<port> of a running companion service")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--self-test", action="store_true", help="measure against a local loopback server instead of a real Pi")
    args = parser.parse_args()

    if args.self_test:
        result = asyncio.run(_run_self_test(args.count))
    elif args.uri:
        result = asyncio.run(measure_ws_latency(args.uri, count=args.count))
    else:
        parser.error("pass --uri ws://<pi-ip>:<port> or --self-test")
        return

    print(result.report())
    sys.exit(0 if result.passes() else 1)


if __name__ == "__main__":
    main()
