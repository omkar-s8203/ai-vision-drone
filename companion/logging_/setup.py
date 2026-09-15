from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "companion.log", maxBytes=10_000_000, backupCount=5
    )
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
