"""Tests for tools/ws_latency_benchmark.py.

measure_ws_latency() is exercised against a real GroundStationLink over a
real WebSocket (not a fake transport) - the point of this tool is to
measure the actual transport's round-trip time, so a fake in-process
transport would defeat the purpose. WsLatencyResult's pass/fail math is
also covered directly with synthetic samples.
"""

import pytest

from companion.comms.transport import WebSocketTransport
from companion.comms.ws_server import GroundStationLink
from tools.ws_latency_benchmark import MAX_WS_RTT_MS, WsLatencyResult, measure_ws_latency

WS_PORT = 18791


@pytest.mark.asyncio
async def test_measure_ws_latency_records_a_real_round_trip_per_ping():
    transport = WebSocketTransport(host="127.0.0.1", port=WS_PORT)
    link = GroundStationLink(transport)
    await link.start()
    try:
        result = await measure_ws_latency(f"ws://127.0.0.1:{WS_PORT}", count=5)
    finally:
        await link.stop()

    assert result.count == 5
    assert all(sample >= 0.0 for sample in result.samples_ms)
    assert result.mean_ms is not None
    assert result.p95_ms is not None


def test_result_passes_when_p95_is_under_the_threshold():
    result = WsLatencyResult(samples_ms=[5.0, 6.0, 7.0, 8.0, 9.0])
    assert result.p95_ok()
    assert result.passes()
    assert "PASS" in result.report()


def test_result_fails_when_p95_is_over_the_threshold():
    result = WsLatencyResult(samples_ms=[5.0] * 19 + [MAX_WS_RTT_MS + 100.0])
    assert not result.p95_ok()
    assert not result.passes()
    assert "FAIL" in result.report()


def test_result_with_no_samples_reports_cleanly_without_crashing():
    result = WsLatencyResult()
    assert result.mean_ms is None
    assert result.p95_ms is None
    assert not result.passes()
    assert "No round trips" in result.report()
