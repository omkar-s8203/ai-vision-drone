from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


DEFAULT_MAX_SESSIONS = 50


class SessionRecorder:
    """Appends a replayable timeline of MAVLink state, tracker transitions,
    and guidance decisions to a per-session JSONL file, so any flight/test
    decision can be reconstructed offline (docs plan M11)."""

    def __init__(self, session_dir: Path, max_sessions: int = DEFAULT_MAX_SESSIONS) -> None:
        session_dir.mkdir(parents=True, exist_ok=True)
        self._prune_old_sessions(session_dir, max_sessions)
        filename = f"session_{int(time.time())}.jsonl"
        self._path = session_dir / filename
        self._file = self._path.open("a", encoding="utf-8")

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
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
