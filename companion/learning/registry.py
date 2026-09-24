from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Taught objects get class ids well above the detector's own label range (COCO
# is 0-89) so they can never collide with a real detection's class id.
CUSTOM_CLASS_ID_BASE = 10_000
MAX_NAME_LEN = 32
MAX_OBJECTS = 100
MAX_REAL_SIZE_M = 50.0


def slugify(name) -> Optional[str]:
    """Filesystem- and label-safe name: lowercase letters, digits, `_` and `-`
    only. Returns None if nothing usable is left. This is what keeps an
    app-supplied name from ever becoming a path (`../..`) or a control string."""
    if not isinstance(name, str):
        return None
    slug = re.sub(r"[^a-z0-9_-]+", "_", name.strip().lower()).strip("_-")
    slug = slug[:MAX_NAME_LEN].strip("_-")
    return slug or None


def _valid_size(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or number > MAX_REAL_SIZE_M:
        return None
    return number


@dataclass
class TaughtObject:
    name: str                       # slug - also the detection label / dataset folder
    class_id: int                   # CUSTOM_CLASS_ID_BASE + index
    real_width_m: Optional[float]   # needed for distance; None = distance unknown
    real_height_m: Optional[float]
    created_ts: float


class TaughtObjectRegistry:
    """Persistent list of objects the operator has taught the drone, stored as
    one small JSON file next to the photos. Re-teaching an existing name keeps
    its class id (and updates its real size), so a dataset built across several
    sessions stays one class."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._objects: dict[str, TaughtObject] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return
        for entry in raw.get("objects", []):
            try:
                obj = TaughtObject(**entry)
            except TypeError:
                continue
            self._objects[obj.name] = obj

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"objects": [asdict(o) for o in self._objects.values()]}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)  # atomic: a power cut never leaves a half-written registry

    def all(self) -> list[TaughtObject]:
        return sorted(self._objects.values(), key=lambda o: o.class_id)

    def get(self, name: str) -> Optional[TaughtObject]:
        return self._objects.get(name)

    def register(self, name, real_width_m=None, real_height_m=None) -> Optional[TaughtObject]:
        slug = slugify(name)
        if slug is None:
            return None
        width = _valid_size(real_width_m)
        height = _valid_size(real_height_m)
        existing = self._objects.get(slug)
        if existing is not None:
            existing.real_width_m = width if width is not None else existing.real_width_m
            existing.real_height_m = height if height is not None else existing.real_height_m
            self._save()
            return existing
        if len(self._objects) >= MAX_OBJECTS:
            return None
        used = {o.class_id for o in self._objects.values()}
        class_id = CUSTOM_CLASS_ID_BASE
        while class_id in used:
            class_id += 1
        obj = TaughtObject(slug, class_id, width, height, time.time())
        self._objects[slug] = obj
        self._save()
        return obj
