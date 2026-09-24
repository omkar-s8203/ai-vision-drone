import asyncio
import json

import pytest
import websockets

from tools.live_monitor import EVENT_TYPES, Throttle, format_line, monitor, summarize


def _env(msg_type, payload):
    return json.dumps({"type": msg_type, "seq": 1, "ts": 0.0, "payload": payload})


def test_telemetry_line_shows_the_key_flight_values_and_tolerates_missing_ones():
    line = summarize("telemetry", {
        "fc_mode": "GUIDED", "armed": True, "alt_m": 9.87, "groundspeed_mps": 1.2, "heading_deg": 270,
        "battery_voltage_v": 15.8, "battery_remaining_pct": 71, "gps_fix_type": 3, "satellites_visible": 12,
        "hdop": 0.9, "distance_to_home_m": 42.0, "fence_breached": False, "rc_rssi_pct": 88,
    })
    for expected in ("mode=GUIDED", "armed=True", "alt=9.9m", "hdg=270", "15.8V/71%", "gps=3/12sat", "fence=ok"):
        assert expected in line
    assert "--" in summarize("telemetry", {})            # everything unknown, no crash
    assert "BREACH" in summarize("telemetry", {"fence_breached": True})


def test_tracking_line_shows_commands_and_why_guidance_is_blocked_or_holding():
    line = summarize("tracking_update", {
        "state": "TRACKING", "supervisor_state": "FOLLOWING", "guidance_allowed": True, "distance_m": 6.04,
        "commanded_vx_mps": 0.5, "commanded_vy_mps": 0.0, "commanded_vz_mps": -0.25, "commanded_yaw_rate_rads": 0.1,
        "guidance_sent": True, "guidance_reason": None, "guidance_hold": "target_unseen", "teaching": "red_box",
        "teach_samples": 12,
    })
    for expected in ("track=TRACKING", "sup=FOLLOWING", "dist=6.0m", "vx=+0.50", "vz=-0.25", "sent=True",
                     "HOLD=target_unseen", "TEACHING=red_box(12 photos)"):
        assert expected in line
    assert "BLOCKED=rc_override" in summarize("tracking_update", {"guidance_reason": "rc_override"})
    assert "cmd[" not in summarize("tracking_update", {"state": "IDLE"})   # no command -> no command block


def test_health_and_detection_lines():
    assert "all ok" in summarize("health", {"camera_ok": True, "mavlink_ok": True, "fps": 29.7})
    assert "PROBLEM: camera,mavlink" in summarize("health", {"camera_ok": False, "mavlink_ok": False})
    assert summarize("detections_update", {"detections": [{"class_name": "person"}, {"class_name": "person"}, {"class_name": "car"}]}) \
        == "3 object(s): person x2, car"
    assert summarize("detections_update", {"detections": []}) == "0 object(s)"


def test_one_off_events_are_flagged_and_readable():
    assert "REJECTED" in summarize("arm_command_result", {"armed_requested": False, "accepted": False})
    assert "DISARM" in summarize("arm_command_result", {"armed_requested": False, "accepted": True})
    assert "NOT CONFIRMED" in summarize("mode_change_result", {"mode": "RTL", "confirmed": False})
    assert "teach OK: red_box" in summarize("teach_result", {"ok": True, "name": "red_box", "has_distance": True})
    assert "teach FAILED: bad_name" in summarize("teach_result", {"ok": False, "reason": "bad_name"})
    assert "LAND CONFIRMATION" in summarize("land_confirmation_request", {"battery_remaining_pct": 15})


def test_the_huge_video_signalling_payload_is_not_dumped():
    assert "omitted" in summarize("webrtc_answer", {"sdp": "x" * 5000})


def test_unknown_types_and_malformed_payloads_never_crash():
    assert summarize("something_new", {"a": 1}) == '{"a": 1}'
    for msg_type in ("telemetry", "tracking_update", "health", "detections_update", "arm_command_result"):
        summarize(msg_type, None)
        summarize(msg_type, "not a dict")


def test_a_line_starts_with_a_timestamp_and_the_type():
    assert format_line("health", {"fps": 30.0}, wall=0.0).split()[1] == "health"
    assert format_line("health", {}, raw='{"x":1}').endswith('{"x":1}')


# --- throttling: readable, but never hides something that matters -----------

class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_high_rate_types_are_limited_per_type():
    clock = _Clock()
    throttle = Throttle(rate_hz=2.0, clock=clock)
    printed = 0
    for i in range(60):                       # 30 Hz for 2 seconds
        clock.t = i / 30
        printed += throttle.should_print("detections_update", {})
    assert 3 <= printed <= 5                  # ~2 per second, not 60
    clock.t = 5.0
    assert throttle.should_print("health", {})  # a different type has its own budget


def test_rate_zero_prints_everything():
    throttle = Throttle(rate_hz=0)
    assert all(throttle.should_print("detections_update", {}) for _ in range(100))


@pytest.mark.parametrize("field,before,after", [
    ("fc_mode", "GUIDED", "RTL"),
    ("armed", False, True),
])
def test_a_flight_state_change_is_printed_immediately_even_inside_the_throttle_window(field, before, after):
    clock = _Clock()
    throttle = Throttle(rate_hz=1.0, clock=clock)
    assert throttle.should_print("telemetry", {field: before})
    clock.t = 0.05
    assert not throttle.should_print("telemetry", {field: before})     # unchanged: throttled
    clock.t = 0.10
    assert throttle.should_print("telemetry", {field: after})          # changed: shown at once


@pytest.mark.parametrize("field,before,after", [
    ("supervisor_state", "FOLLOWING", "SAFE"),
    ("guidance_reason", None, "rc_override"),
    ("guidance_hold", None, "target_unseen"),
    ("state", "TRACKING", "REACQUIRE"),
    ("teaching", None, "red_box"),
])
def test_a_guidance_change_is_printed_immediately(field, before, after):
    clock = _Clock()
    throttle = Throttle(rate_hz=0.5, clock=clock)
    throttle.should_print("tracking_update", {field: before})
    clock.t = 0.03
    assert throttle.should_print("tracking_update", {field: after})


def test_events_are_never_throttled():
    throttle = Throttle(rate_hz=0.01)
    for event in EVENT_TYPES:
        assert throttle.should_print(event, {}) and throttle.should_print(event, {})


# --- against a real WebSocket server ----------------------------------------

@pytest.mark.asyncio
async def test_it_prints_the_streamed_messages_and_never_sends_anything_back():
    """Read-only matters: any message from this tool would count as the phone being alive."""
    received_from_monitor = []

    async def handler(ws):
        async for message in ws:
            received_from_monitor.append(message)

    async def serve_and_stream(ws):
        for i in range(3):
            await ws.send(_env("telemetry", {"fc_mode": "GUIDED", "alt_m": 10.0 + i}))
        await ws.send(_env("mode_change_result", {"mode": "RTL", "confirmed": True}))
        await ws.send("not json at all")
        await ws.send(_env("health", {"fps": 30.0}))
        await handler(ws)

    lines = []
    async with websockets.serve(serve_and_stream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        printed = await asyncio.wait_for(
            monitor(f"ws://127.0.0.1:{port}", rate_hz=0, out=lines.append, max_messages=5), timeout=10
        )
    text = "\n".join(lines)
    assert printed == 5
    assert "-- connected (read-only" in text
    assert text.count("telemetry") == 3 and "alt=12.0m" in text
    assert "flight mode RTL: confirmed" in text
    assert "unparseable message" in text and "fps=30.0" in text
    assert received_from_monitor == []


@pytest.mark.asyncio
async def test_the_only_filter_hides_other_types():
    async def serve(ws):
        await ws.send(_env("telemetry", {}))
        await ws.send(_env("health", {"fps": 1.0}))
        await ws.send(_env("health", {"fps": 2.0}))
        await asyncio.sleep(0.2)

    lines = []
    async with websockets.serve(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        await asyncio.wait_for(
            monitor(f"ws://127.0.0.1:{port}", only={"health"}, rate_hz=0, out=lines.append, max_messages=2), timeout=10
        )
    assert not any(" telemetry " in line for line in lines)
    assert sum(" health " in line for line in lines) == 2


@pytest.mark.asyncio
async def test_it_keeps_retrying_when_the_pi_is_not_reachable(monkeypatch):
    """(A real refused connection takes ~2 s to be reported on Windows, so the failure is injected.)"""
    attempts = []

    def refuse(uri):
        attempts.append(uri)
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(websockets, "connect", refuse)
    lines = []
    task = asyncio.create_task(monitor("ws://pi:8765", out=lines.append, reconnect_delay_s=0.05))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(attempts) >= 3
    assert sum("retrying" in line and "ConnectionRefusedError" in line for line in lines) >= 3
