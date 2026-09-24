from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np

from companion.learning.registry import TaughtObject
from companion.vision.detector import BBox

log = logging.getLogger(__name__)


class DatasetRecorder:
    """Saves labelled photos of a taught object while it is being tracked, in
    YOLO format (one `.txt` per image: `0 cx cy w h`, all normalised), for later
    offline training. Deliberately conservative: it only saves when the track
    still looks like the object, skips near-duplicates, and stops at a per-object
    and total size cap. JPEG encoding runs on one background thread so the
    control loop is never blocked by disk or compression.

    Known limitation, stated plainly: each image labels only the taught object -
    anything else visible in the frame (e.g. a person next to a backpack) is
    unlabelled, which trains the model to ignore it. Teach one object at a time
    against varied backgrounds, and merge with a general dataset for training
    (docs/teach-and-train.md).
    """

    def __init__(self, root: Path, limits: dict) -> None:
        self.root = Path(root)
        self.limits = limits
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset-writer")
        self._pending: list[Future] = []
        self._obj: Optional[TaughtObject] = None
        self._dir: Optional[Path] = None
        self._count = 0
        self._last_ts = -1e9
        self._last_save_ts = -1e9
        self._last_bbox: Optional[BBox] = None

    @property
    def is_active(self) -> bool:
        return self._obj is not None

    @property
    def sample_count(self) -> int:
        return self._count

    def start(self, obj: TaughtObject) -> None:
        self.stop()
        self._obj = obj
        self._dir = self.root / obj.name
        (self._dir / "images").mkdir(parents=True, exist_ok=True)
        (self._dir / "labels").mkdir(parents=True, exist_ok=True)
        self._count = len(list((self._dir / "images").glob("*.jpg")))  # numbering continues across sessions
        self._last_ts = -1e9
        self._last_save_ts = -1e9
        self._last_bbox = None
        self._write_meta(obj)

    def stop(self) -> None:
        self.wait()
        self._obj = None
        self._dir = None

    def wait(self) -> None:
        """Blocks until queued writes finish (tests, shutdown)."""
        for future in self._pending:
            try:
                future.result(timeout=10)
            except Exception:
                log.exception("Dataset write failed")
        self._pending.clear()

    def _write_meta(self, obj: TaughtObject) -> None:
        assert self._dir is not None
        (self._dir / "meta.json").write_text(
            json.dumps(
                {
                    "name": obj.name,
                    "class_id": obj.class_id,
                    "real_width_m": obj.real_width_m,
                    "real_height_m": obj.real_height_m,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _total_mb(self) -> float:
        total = 0
        if self.root.exists():
            for path in self.root.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        return total / (1024 * 1024)

    def _is_different_enough(self, bbox: BBox, frame_width: int, ts: float) -> bool:
        if self._last_bbox is None:
            return True
        if ts - self._last_save_ts >= self.limits["min_repeat_s"]:
            return True
        shift = max(abs(bbox.cx - self._last_bbox.cx), abs(bbox.cy - self._last_bbox.cy))
        if shift >= self.limits["min_center_shift_frac"] * frame_width:
            return True
        old_area = max(self._last_bbox.area, 1.0)
        return abs(bbox.area - old_area) / old_area >= self.limits["min_scale_change_frac"]

    def maybe_save(
        self, frame_bgr: Optional[np.ndarray], bbox: BBox, ts: float, similarity: Optional[float]
    ) -> bool:
        """Queues a sample if every gate passes; returns whether it did."""
        if self._obj is None or self._dir is None or frame_bgr is None:
            return False
        if similarity is None or similarity < self.limits["min_similarity"]:
            return False
        if self._count >= self.limits["max_samples_per_object"]:
            return False
        if ts - self._last_ts < self.limits["sample_interval_s"]:
            return False
        height, width = frame_bgr.shape[:2]
        if bbox.w <= 1 or bbox.h <= 1 or bbox.x < 0 or bbox.y < 0 or bbox.x + bbox.w > width or bbox.y + bbox.h > height:
            return False  # a box touching/leaving the frame is a poor, clipped label
        if not self._is_different_enough(bbox, width, ts):
            return False
        if self._total_mb() >= self.limits["max_total_mb"]:
            return False

        index = self._count
        self._count += 1
        self._last_ts = ts
        self._last_save_ts = ts
        self._last_bbox = bbox
        image = frame_bgr.copy()  # the camera may overwrite its buffer before the thread runs
        self._pending.append(self._executor.submit(self._write, self._dir, self._obj.name, index, image, bbox))
        self._pending = [f for f in self._pending if not f.done()]
        return True

    def _write(self, directory: Path, name: str, index: int, image: np.ndarray, bbox: BBox) -> None:
        import cv2

        height, width = image.shape[:2]
        stem = f"{name}_{int(time.time())}_{index:05d}"
        ok = cv2.imwrite(
            str(directory / "images" / f"{stem}.jpg"),
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(self.limits["jpeg_quality"])],
        )
        if not ok:
            log.error("Failed to write dataset image %s", stem)
            return
        cx, cy = bbox.cx / width, bbox.cy / height
        (directory / "labels" / f"{stem}.txt").write_text(
            f"0 {cx:.6f} {cy:.6f} {bbox.w / width:.6f} {bbox.h / height:.6f}\n", encoding="utf-8"
        )
