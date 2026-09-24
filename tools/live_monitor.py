"""Live, continuous view of everything the Pi sends to the app - in a terminal.

Connects to the Pi's WebSocket (the same stream the Android app reads) and prints one
readable line per message: telemetry, tracking/guidance, health, detections, and one-off
events (arm results, mode-change results, teach results). Reconnects by itself.

Run on your laptop (cmd / PowerShell), joined to the Pi's WiFi:

    pip install websockets
    python tools/live_monitor.py --uri ws://<pi-ip>:8765

or on the Pi itself, inside the project venv:

    python tools/live_monitor.py --uri ws://127.0.0.1:8765

Useful options:

    --only tracking_update,telemetry   only these message types
    --rate 2                           at most 2 lines/second per type (default). 0 = every message
    --raw                              print the full JSON instead of the summary

High-rate types (tracking, detections, telemetry, health arrive every camera frame) are
throttled so the screen stays readable - BUT a change in the flight mode, arm state, guidance
state, block reason, hold reason or teaching is always printed immediately, and one-off events
are never throttled, so nothing important is skipped.

READ-ONLY BY DESIGN: this tool never sends a message. That matters - the Pi decides whether the
operator's phone is still alive from the messages it receives, so a monitor that sent anything
(even a ping) could keep the Pi believing the phone was connected after the phone had died.

The Pi's own log lines (start-up checks, failsafes, errors) are separate - see the commands in
docs/lab-test-checklist.md ("Handy commands"): `journalctl -u ai-vision-drone -f` on the Pi.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Callable, Optional

# Printed immediately, never throttled: they happen once, and each matters.
EVENT_TYPES = {
    "arm_command_result",
    "mode_change_result",
    "teach_result",
    "land_confirmation_request",
    "ack",
    "error",
}

# Per type: the fields whose change forces an immediate line even inside the throttle window.
EDGE_FIELDS = {
    "telemetry": ("fc_mode", "armed", "fence_breached", "gps_fix_type"),
    "tracking_update": (
        "state", "supervisor_state", "guidance_allowed", "guidance_reason", "guidance_hold", "teaching",
    ),
}


def _num(value, fmt: str = "{:.1f}", missing: str = "--") -> str:
    return missing if value is None else fmt.format(value)


def summarize(msg_type: str, payload: dict) -> str:
    """One compact line for a message. Never raises on a missing/odd field."""
    p = payload if isinstance(payload, dict) else {}
    if msg_type == "telemetry":
        return (
            f"mode={p.get('fc_mode')} armed={p.get('armed')} alt={_num(p.get('alt_m'))}m "
            f"gs={_num(p.get('groundspeed_mps'))}m/s hdg={_num(p.get('heading_deg'), '{:.0f}')} "
            f"batt={_num(p.get('battery_voltage_v'), '{:.1f}')}V/{_num(p.get('battery_remaining_pct'), '{:.0f}')}% "
            f"gps={p.get('gps_fix_type')}/{p.get('satellites_visible')}sat hdop={_num(p.get('hdop'))} "
            f"home={_num(p.get('distance_to_home_m'), '{:.0f}')}m fence={'BREACH' if p.get('fence_breached') else 'ok'} "
            f"rssi={p.get('rc_rssi_pct')}"
        )
    if msg_type == "tracking_update":
        line = (
            f"track={p.get('state')} sup={p.get('supervisor_state')} allowed={p.get('guidance_allowed')} "
            f"dist={_num(p.get('distance_m'))}m"
        )
        if p.get("commanded_vx_mps") is not None:
            line += (
                f" cmd[vx={_num(p.get('commanded_vx_mps'), '{:+.2f}')} vy={_num(p.get('commanded_vy_mps'), '{:+.2f}')} "
                f"vz={_num(p.get('commanded_vz_mps'), '{:+.2f}')} yaw={_num(p.get('commanded_yaw_rate_rads'), '{:+.2f}')}] "
                f"sent={p.get('guidance_sent')}"
            )
        for key, label in (("guidance_reason", "BLOCKED"), ("guidance_hold", "HOLD"), ("teaching", "TEACHING")):
            if p.get(key):
                line += f" {label}={p[key]}"
        if p.get("teach_samples") is not None:
            line += f"({p['teach_samples']} photos)"
        return line
    if msg_type == "health":
        flags = [k.replace("_ok", "") for k in ("camera_ok", "ai_ok", "tracker_ok", "mavlink_ok", "video_ok") if p.get(k) is False]
        return (
            f"fps={_num(p.get('fps'))} latency={_num(p.get('latency_ms'), '{:.0f}')}ms temp={_num(p.get('temperature_c'), '{:.0f}')}C "
            f"rec={p.get('recording')} " + ("PROBLEM: " + ",".join(flags) if flags else "all ok")
        )
    if msg_type == "detections_update":
        names = [d.get("class_name", "?") for d in p.get("detections", []) if isinstance(d, dict)]
        counts: dict[str, int] = {}
        for n in names:
            counts[n] = counts.get(n, 0) + 1
        shown = ", ".join(f"{n} x{c}" if c > 1 else n for n, c in counts.items())
        return f"{len(names)} object(s){': ' + shown if shown else ''}"
    if msg_type == "grid_search_update":
        return f"active={p.get('active')} phase={p.get('phase')} leg={p.get('current_index')}/{len(p.get('waypoints', []))}"
    if msg_type == "recording_state":
        return f"recording={p.get('recording')} {_num(p.get('duration_s'), '{:.0f}')}s"
    if msg_type == "arm_command_result":
        return f"*** {'ARM' if p.get('armed_requested') else 'DISARM'} {'accepted' if p.get('accepted') else 'REJECTED'} by the FC"
    if msg_type == "mode_change_result":
        return f"*** flight mode {p.get('mode')}: {'confirmed' if p.get('confirmed') else 'NOT CONFIRMED by the FC'}"
    if msg_type == "teach_result":
        if p.get("ok"):
            return f"*** teach OK: {p.get('name')} (distance {'known' if p.get('has_distance') else 'unknown - no size given'})"
        return f"*** teach FAILED: {p.get('reason')}"
    if msg_type == "land_confirmation_request":
        return f"*** LAND CONFIRMATION NEEDED: {json.dumps(p)}"
    if msg_type in ("webrtc_answer", "webrtc_offer"):
        return "(video signalling, sdp omitted)"
    return json.dumps(p)


class Throttle:
    """Per-type rate limit that always lets through events and important state changes."""

    def __init__(self, rate_hz: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.min_interval = 0.0 if rate_hz <= 0 else 1.0 / rate_hz
        self.clock = clock
        self._last_print: dict[str, float] = {}
        self._last_edge: dict[str, tuple] = {}

    def should_print(self, msg_type: str, payload: dict) -> bool:
        if msg_type in EVENT_TYPES:
            return True
        now = self.clock()
        edge_fields = EDGE_FIELDS.get(msg_type)
        changed = False
        if edge_fields and isinstance(payload, dict):
            edge = tuple(payload.get(f) for f in edge_fields)
            changed = msg_type in self._last_edge and edge != self._last_edge[msg_type]
            self._last_edge[msg_type] = edge
        if changed or now - self._last_print.get(msg_type, -1e9) >= self.min_interval:
            self._last_print[msg_type] = now
            return True
        return False


def format_line(msg_type: str, payload: dict, raw: Optional[str] = None, wall: Optional[float] = None) -> str:
    wall = time.time() if wall is None else wall
    stamp = time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int((wall % 1) * 1000):03d}"
    body = raw if raw is not None else summarize(msg_type, payload)
    return f"{stamp}  {msg_type:<18} {body}"


async def monitor(
    uri: str,
    only: Optional[set[str]] = None,
    rate_hz: float = 2.0,
    raw: bool = False,
    out: Callable[[str], None] = print,
    max_messages: Optional[int] = None,
    reconnect_delay_s: float = 2.0,
) -> int:
    """Prints until interrupted (or `max_messages` lines, for tests). Returns lines printed."""
    import websockets

    throttle = Throttle(rate_hz)
    printed = 0
    while True:
        try:
            out(f"-- connecting to {uri} ...")
            async with websockets.connect(uri) as ws:
                out("-- connected (read-only: this tool never sends anything)")
                async for message in ws:
                    try:
                        envelope = json.loads(message)
                        msg_type = str(envelope.get("type", "?"))
                        payload = envelope.get("payload", {})
                    except (ValueError, AttributeError):
                        out(f"?? unparseable message: {str(message)[:200]}")
                        continue
                    if only and msg_type not in only:
                        continue
                    if not throttle.should_print(msg_type, payload):
                        continue
                    out(format_line(msg_type, payload, raw=message if raw else None))
                    printed += 1
                    if max_messages is not None and printed >= max_messages:
                        return printed
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            out(f"-- connection lost/failed ({type(exc).__name__}: {exc}); retrying in {reconnect_delay_s:.0f}s")
        if max_messages is not None and printed >= max_messages:
            return printed
        await asyncio.sleep(reconnect_delay_s)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default="ws://127.0.0.1:8765", help="ws://<pi-ip>:8765")
    parser.add_argument("--only", default="", help="comma-separated message types to show")
    parser.add_argument("--rate", type=float, default=2.0, help="max lines per second per type; 0 = all")
    parser.add_argument("--raw", action="store_true", help="print full JSON")
    args = parser.parse_args(argv)
    only = {t.strip() for t in args.only.split(",") if t.strip()} or None
    try:
        asyncio.run(monitor(args.uri, only=only, rate_hz=args.rate, raw=args.raw))
    except KeyboardInterrupt:
        print("\n-- stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
