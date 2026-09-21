from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


DEFAULT_MAX_SESSIONS = 50


class SessionRecorder:
    """Appends a replayable timeline of MAVLink state, tracker transitions,
    and guidance decisions to a per-session JSONL file, so any flight/test
    decision can be reconstructed offline (docs plan M11).

    record() is called from both plain sync callback sites (e.g.
    CompanionOrchestrator._on_abort, invoked directly from
    GroundStationLink._dispatch) and from inside the async per-frame hot
    loop (process_frame(), sometimes several times per frame) - so it can't
    simply become `async def` without changing every call site's own
    signature (several of which are registered as plain callables in
    GroundStationLink._handlers and can't be coroutines). Instead the
    blocking write+flush itself is offloaded to a single-worker thread
    pool: record() returns immediately, never blocking the event loop
    thread, while the single worker preserves call order (submissions are
    processed FIFO, same as writing inline would have been). close() drains
    the pool before closing the file, so a normal shutdown never drops a
    pending write - the only real durability trade-off is the (very small)
    window between a submit() and that worker thread actually running it.
    """

    def __init__(self, session_dir: Path, max_sessions: int = DEFAULT_MAX_SESSIONS) -> None:
        session_dir.mkdir(parents=True, exist_ok=True)
        self._prune_old_sessions(session_dir, max_sessions)
        filename = f"session_{int(time.time())}.jsonl"
        self._path = session_dir / filename
        self._file = self._path.open("a", encoding="utf-8")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-recorder")

    @staticmethod
    def _prune_old_sessions(session_dir: Path, max_sessions: int) -> None:
        """Session files previously accumulated forever - disk space on the
        Pi is finite (docs plan M11's testing section calls this out
        explicitly), and companion.log already rotates via
        RotatingFileHandler (see logging_/setup.py) but this recorder never
        got the same treatment. Keeps the most recent (max_sessions - 1)
        existing files, leaving room for the new one this call is about to
        create. Filenames embed a unix timestamp, so lexicographic sort
        order matches chronological order."""
        sessions = sorted(session_dir.glob("session_*.jsonl"))
        excess = max(0, len(sessions) - max(0, max_sessions - 1))
        for old_file in sessions[:excess]:
            old_file.unlink(missing_ok=True)

    def record(self, event_type: str, **fields: Any) -> None:
        entry = {"ts": time.time(), "event": event_type, **fields}
        self._executor.submit(self._write_entry, entry)

    def _write_entry(self, entry: dict) -> None:
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        self._file.close()
