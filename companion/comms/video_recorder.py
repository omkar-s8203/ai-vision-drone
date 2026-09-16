from __future__ import annotations

import time
from pathlib import Path
from typing import Optional


class VideoRecorder:
    """Writes camera frames to an MP4 file on the Pi's own storage, so
    footage is captured locally regardless of network/streaming conditions
    (unlike the WebRTC feed, which can drop or degrade with WiFi range).
    Only meaningful with a real frame source (hardware mode) - a backend
    with no real image data (SyntheticCamera) is simply never asked to
    record.
    """

    def __init__(self, output_dir: Path, fps: int) -> None:
        self.output_dir = output_dir
        self.fps = fps
        self._writer = None
        self._path: Optional[Path] = None
        self._started_ts: Optional[float] = None

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    @property
    def current_path(self) -> Optional[Path]:
        return self._path

    @property
    def duration_s(self) -> float:
        if self._started_ts is None:
            return 0.0
        return time.monotonic() - self._started_ts

    def start(self, width: int, height: int) -> Path:
        if self.is_recording:
            return self._path  # already recording - idempotent, not an error
        import cv2  # lazy import: only needed if recording is actually used

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.output_dir / f"recording_{int(time.time())}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(str(self._path), fourcc, self.fps, (width, height))
        self._started_ts = time.monotonic()
        return self._path

    def write(self, frame_bgr) -> None:
        if self._writer is not None and frame_bgr is not None:
            self._writer.write(frame_bgr)

    def stop(self) -> Optional[Path]:
        if self._writer is None:
            return None
        self._writer.release()
        self._writer = None
        self._started_ts = None
        path = self._path
        self._path = None
        return path
