import json

from companion.logging_.session_recorder import SessionRecorder


def test_record_writes_one_jsonl_entry_per_call(tmp_path):
    recorder = SessionRecorder(tmp_path)
    recorder.record("target_selected", target_id=1, class_name="person")
    recorder.record("mode_changed", mode="follow")
    recorder.close()

    lines = recorder._path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "target_selected"
    assert first["target_id"] == 1
    assert first["class_name"] == "person"
    assert "ts" in first
    second = json.loads(lines[1])
    assert second["event"] == "mode_changed"
    assert second["mode"] == "follow"


def test_does_not_prune_when_under_the_limit(tmp_path):
    for i in range(3):
        (tmp_path / f"session_{1000 + i}.jsonl").write_text("{}\n", encoding="utf-8")

    recorder = SessionRecorder(tmp_path, max_sessions=10)
    recorder.close()

    remaining = sorted(p.name for p in tmp_path.glob("session_*.jsonl"))
    assert len(remaining) == 4  # the 3 pre-existing files plus the new one
    assert "session_1000.jsonl" in remaining


def test_prunes_oldest_sessions_beyond_max(tmp_path):
    """Session files previously accumulated forever - disk space on the Pi
    is finite (docs plan M11). This proves the oldest files (by the unix
    timestamp embedded in their filename) are deleted first, and that
    exactly max_sessions files remain once the new session is created."""
    for i in range(5):
        (tmp_path / f"session_{1000 + i}.jsonl").write_text("{}\n", encoding="utf-8")

    recorder = SessionRecorder(tmp_path, max_sessions=3)
    recorder.close()

    remaining = sorted(p.name for p in tmp_path.glob("session_*.jsonl"))
    assert len(remaining) == 3
    # The two oldest (1000, 1001) should be gone; the two newest
    # pre-existing ones (1003, 1004) plus the brand-new session survive.
    assert "session_1000.jsonl" not in remaining
    assert "session_1001.jsonl" not in remaining
    assert "session_1003.jsonl" in remaining
    assert "session_1004.jsonl" in remaining


def test_record_offloads_writes_without_losing_order_or_entries(tmp_path):
    """record() offloads its write+flush to a background thread pool so it
    never blocks the caller (the async per-frame hot loop, or a plain sync
    handler callback - see the class docstring) - this proves that
    offloading doesn't silently drop or reorder entries under a burst of
    rapid calls, and that close() waits for all of them to actually land
    before returning."""
    recorder = SessionRecorder(tmp_path)
    for i in range(50):
        recorder.record("tick", i=i)
    recorder.close()

    lines = recorder._path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    assert [json.loads(line)["i"] for line in lines] == list(range(50))


def test_prune_handles_an_empty_or_fresh_session_dir(tmp_path):
    """Regression guard for the off-by-one in max(0, max_sessions - 1): a
    fresh directory with nothing to prune must not raise or delete the
    file this same call is about to create."""
    recorder = SessionRecorder(tmp_path, max_sessions=1)
    recorder.record("hello")
    recorder.close()

    remaining = list(tmp_path.glob("session_*.jsonl"))
    assert len(remaining) == 1
