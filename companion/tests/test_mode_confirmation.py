import json
from unittest.mock import patch

import pytest

from companion.mavlink.bridge import MODE_MAX_ATTEMPTS, MODE_RETRY_AFTER_S, MavlinkBridge
from companion.tests.test_tracking_safety_orchestrator import _build, _frame

RTL, LOITER, GUIDED = 6, 5, 4


def _bridge(fc_mode="GUIDED"):
    with patch("companion.mavlink.bridge.mavutil"):
        bridge = MavlinkBridge("udpin:127.0.0.1:14797")
        bridge.connect()
    conn = bridge._conn
    conn.target_system = 1
    conn.target_component = 1
    bridge.telemetry.fc_mode = fc_mode
    return bridge, conn


def _sent_modes(conn):
    return [c.args[-1] for c in conn.mav.set_mode_send.call_args_list]


def test_a_request_is_confirmed_when_the_fc_reports_the_new_mode():
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("RTL")
    bridge.telemetry.fc_mode = "RTL"
    bridge.check_pending_mode(now=1e9)
    assert bridge.pending_mode_result == {"mode": "RTL", "confirmed": True}
    assert _sent_modes(conn) == [RTL]
    bridge.pending_mode_result = None
    bridge.check_pending_mode(now=2e9)
    assert bridge.pending_mode_result is None  # resolved once, not repeatedly


def test_an_unconfirmed_request_is_re_sent_only_after_the_retry_delay():
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("RTL")
    sent_at = bridge._pending_mode["sent_ts"]
    bridge.check_pending_mode(now=sent_at + MODE_RETRY_AFTER_S - 0.1)
    assert _sent_modes(conn) == [RTL]
    bridge.check_pending_mode(now=sent_at + MODE_RETRY_AFTER_S + 0.1)
    assert _sent_modes(conn) == [RTL, RTL]
    assert bridge.pending_mode_result is None  # still waiting, not failed yet


def test_after_the_maximum_attempts_it_is_reported_as_not_confirmed():
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("RTL")
    t = bridge._pending_mode["sent_ts"]
    for _ in range(MODE_MAX_ATTEMPTS + 3):
        t += MODE_RETRY_AFTER_S + 0.1
        bridge.check_pending_mode(now=t)
    assert len(_sent_modes(conn)) == MODE_MAX_ATTEMPTS          # never a fourth send
    assert bridge.pending_mode_result == {"mode": "RTL", "confirmed": False}
    assert bridge._pending_mode is None


def test_a_late_confirmation_still_counts():
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("LOITER")
    t = bridge._pending_mode["sent_ts"] + MODE_RETRY_AFTER_S + 0.1
    bridge.check_pending_mode(now=t)                            # one retry
    bridge.telemetry.fc_mode = "LOITER"
    bridge.check_pending_mode(now=t + 0.1)
    assert bridge.pending_mode_result == {"mode": "LOITER", "confirmed": True}


def test_it_never_fights_the_pilot_who_changed_the_mode_themselves():
    """Requested RTL from GUIDED; before the FC acted, the pilot's switch put it in
    LOITER. Re-sending RTL now would override the pilot."""
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("RTL")
    bridge.telemetry.fc_mode = "LOITER"
    bridge.check_pending_mode(now=bridge._pending_mode["sent_ts"] + 60)
    assert _sent_modes(conn) == [RTL]                           # no re-send
    assert bridge.pending_mode_result is None                   # and no "failed" report
    assert bridge._pending_mode is None


def test_with_rc_override_it_waits_without_re_sending_or_failing():
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("LOITER")
    t = bridge._pending_mode["sent_ts"]
    for _ in range(10):
        t += MODE_RETRY_AFTER_S + 1
        bridge.check_pending_mode(allow_retry=False, now=t)
    assert _sent_modes(conn) == [LOITER]
    assert bridge.pending_mode_result is None
    assert bridge._pending_mode is not None                     # still pending; retries resume when allowed


def test_a_newer_request_replaces_the_older_one():
    bridge, conn = _bridge("GUIDED")
    bridge.set_mode("RTL")
    bridge.set_mode("LOITER")
    assert bridge._pending_mode["mode"] == "LOITER"
    bridge.telemetry.fc_mode = "LOITER"
    bridge.check_pending_mode(now=1e9)
    assert bridge.pending_mode_result == {"mode": "LOITER", "confirmed": True}


def test_an_unknown_mode_name_creates_no_pending_request():
    bridge, conn = _bridge("GUIDED")
    assert bridge.set_mode("NOT_A_MODE") is False
    assert bridge._pending_mode is None
    assert _sent_modes(conn) == []


def test_nothing_pending_is_a_no_op():
    bridge, conn = _bridge("GUIDED")
    bridge.check_pending_mode(now=1e9)
    assert bridge.pending_mode_result is None and _sent_modes(conn) == []


# --- through the orchestrator ------------------------------------------------

def _rtl(conn):
    return [c for c in conn.mav.set_mode_send.call_args_list if c.args[-1] == RTL]


def _mode_results(orch):
    out = []
    for raw in orch.link.transport.sent:
        msg = json.loads(raw)
        if msg["type"] == "mode_change_result":
            out.append(msg["payload"])
    return out


def _expire(orch, seconds=MODE_RETRY_AFTER_S + 0.5):
    orch.mavlink._pending_mode["sent_ts"] -= seconds


@pytest.mark.asyncio
async def test_a_lost_failsafe_rtl_is_retried_and_finally_confirmed(tmp_path):
    """The failsafe latch used to make a single lost RTL request permanent."""
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.battery_remaining_pct = 15
        await orch.process_frame(_frame(0.0, []))
        assert len(_rtl(conn)) == 1
        _expire(orch)
        await orch.process_frame(_frame(1.0, []))
        assert len(_rtl(conn)) == 2
        orch.mavlink.telemetry.fc_mode = "RTL"                  # the FC finally acts
        await orch.process_frame(_frame(2.0, []))
        assert _mode_results(orch) == [{"mode": "RTL", "confirmed": True}]
        assert len(_rtl(conn)) == 2


@pytest.mark.asyncio
async def test_a_mode_change_that_never_happens_is_reported_to_the_app(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.battery_remaining_pct = 15
        await orch.process_frame(_frame(0.0, []))
        for i in range(1, 6):
            if orch.mavlink._pending_mode is not None:
                _expire(orch)
            await orch.process_frame(_frame(float(i), []))
        assert len(_rtl(conn)) == MODE_MAX_ATTEMPTS
        assert _mode_results(orch) == [{"mode": "RTL", "confirmed": False}]


@pytest.mark.asyncio
async def test_no_retries_while_the_pilot_has_stick_override(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        # Not GUIDED, so the orchestrator's own "stick override -> request LOITER" rule stays out of it.
        orch.mavlink.telemetry.fc_mode = "STABILIZE"
        orch.mavlink.set_mode("LOITER")
        orch.mavlink.telemetry.rc_channels = {1: 2000, 2: 1500, 3: 1500, 4: 1500}   # roll deflected
        for i in range(4):
            _expire(orch)
            await orch.process_frame(_frame(float(i), []))
        assert [c.args[-1] for c in conn.mav.set_mode_send.call_args_list] == [LOITER]
        assert _mode_results(orch) == []


@pytest.mark.asyncio
async def test_a_confirmed_guided_request_is_recorded_and_relayed_once(tmp_path):
    with _build(tmp_path) as (orch, _rec, conn):
        orch.mavlink.telemetry.fc_mode = "STABILIZE"
        orch.mavlink.set_mode("GUIDED")
        orch.mavlink.telemetry.fc_mode = "GUIDED"
        await orch.process_frame(_frame(0.0, []))
        await orch.process_frame(_frame(0.1, []))
        assert _mode_results(orch) == [{"mode": "GUIDED", "confirmed": True}]
