from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class SessionRecorder:
    """Appends a replayable timeline of MAVLink state, tracker transitions,
    and guidance decisions to a per-session JSONL file, so any flight/test
    decision can be reconstructed offline (docs plan M11)."""

    def __init__(self, session_dir: Path) -> None:
        session_dir.mkdir(parents=True, exist_ok=True)
        filename = f"session_{int(time.time())}.jsonl"
        self._path = session_dir / filename
        self._file = self._path.open("a", encoding="utf-8")

    def record(self, event_type: str, **fields: Any) -> None:
        entry = {"ts": time.time(), "event": event_type, **fields}
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
