from __future__ import annotations

import logging
import math
from typing import Callable, Optional

import numpy as np

from companion.tracking.base import Tracker, TrackedTarget
from companion.tracking.motion import MotionModel
from companion.vision.detector import BBox, Detection

log = logging.getLogger(__name__)


class TeachError(Exception):
    """The visual tracker could not be started (no frame, no OpenCV tracker)."""


def create_cv_tracker():
    """Best single-object OpenCV tracker available in this install, or None.
    CSRT (best) and KCF only ship in opencv-contrib; the plain
    `opencv-python-headless` this project depends on always has MIL, which is
    weaker but adequate for a short, slow-moving follow (measured ~35 ms/frame
    on a laptop CPU, largely independent of image size - so the orchestrator runs
    it on a worker thread, never inline in the control loop). Install
    `opencv-contrib-python-headless` on the Pi for CSRT."""
    import cv2

    for owner in (getattr(cv2, "legacy", None), cv2):
        if owner is None:
            continue
        for name in ("TrackerCSRT_create", "TrackerKCF_create", "TrackerMIL_create"):
            factory = getattr(owner, name, None)
            if factory is not None:
                return factory()
    return None


def visual_tracking_available() -> bool:
    try:
        return create_cv_tracker() is not None
    except Exception:
        return False


class VisualObjectTracker(Tracker):
    """Follows an operator-drawn box with a class-agnostic OpenCV tracker - for
    objects the on-sensor detector has no class for. It plugs into the same
    `Tracker` interface as the detector-based trackers, so the state machine,
    Follow/Orbit, identity check and REACQUIRE holds all work unchanged; the
    only difference is that it reads pixels (via `frame_provider`) instead of
    detections.

    There is no detector confirming the box is still on the object, so a
    drifting tracker is the main risk. Mitigations: sanity limits on box size
    and shape change, the appearance identity check the orchestrator already
    runs on every tracked frame, a lower speed cap while following it, and no
    automatic re-lock (a lost object must be re-drawn by the operator).
    """

    def __init__(self, frame_provider: Callable[[], Optional[np.ndarray]], limits: dict) -> None:
        self.frame_provider = frame_provider
        self.limits = limits
        self._cv_tracker = None
        self._target: Optional[TrackedTarget] = None
        self._motion: Optional[MotionModel] = None
        self._frame_size = (0, 0)
        # The frame the last update() actually processed - the dataset labels THIS frame,
        # not whatever the camera has captured since (a moving object would be mislabelled).
        self.last_frame: Optional[np.ndarray] = None

    def init_target(self, frame_ts: float, detection: Detection, target_id: int) -> TrackedTarget:
        frame = self.frame_provider()
        if frame is None:
            raise TeachError("no_camera_frame")
        tracker = create_cv_tracker()
        if tracker is None:
            raise TeachError("no_visual_tracker")
        height, width = frame.shape[:2]
        b = detection.bbox
        x, y = max(0, int(b.x)), max(0, int(b.y))
        w, h = min(int(b.w), width - x), min(int(b.h), height - y)
        if w < self.limits["min_box_px"] or h < self.limits["min_box_px"]:
            raise TeachError("box_too_small")
        self._frame_size = (width, height)
        tracker.init(frame, (x, y, w, h))
        self._cv_tracker = tracker
        box = BBox(float(x), float(y), float(w), float(h))
        self._motion = MotionModel(box)
        self._target = TrackedTarget(
            target_id=target_id, bbox=box, confidence=1.0, class_id=detection.class_id,
            class_name=detection.class_name, last_seen_ts=frame_ts, velocity_px_s=(0.0, 0.0),
            smooth_bbox=box,
        )
        return self._target

    def _sane(self, box: BBox, previous: BBox) -> bool:
        values = (box.x, box.y, box.w, box.h)
        if not all(math.isfinite(v) for v in values):
            return False
        if box.w < self.limits["min_box_px"] or box.h < self.limits["min_box_px"]:
            return False
        width, height = self._frame_size
        # At least half the box must still be inside the frame.
        inside_w = max(0.0, min(box.x + box.w, width) - max(box.x, 0.0))
        inside_h = max(0.0, min(box.y + box.h, height) - max(box.y, 0.0))
        if inside_w * inside_h < 0.5 * box.w * box.h:
            return False
        area_ratio = (box.w * box.h) / max(previous.w * previous.h, 1.0)
        factor = self.limits["max_area_change_factor"]
        if area_ratio > factor or area_ratio < 1.0 / factor:
            return False
        aspect_ratio = (box.w / box.h) / max(previous.w / max(previous.h, 1.0), 1e-6)
        factor = self.limits["max_aspect_change_factor"]
        return 1.0 / factor <= aspect_ratio <= factor

    def update(self, frame_ts: float, detections: list[Detection]) -> Optional[TrackedTarget]:
        if self._target is None or self._cv_tracker is None or self._motion is None:
            return None
        frame = self.frame_provider()
        if frame is None:
            return None
        self.last_frame = frame
        try:
            ok, raw = self._cv_tracker.update(frame)
        except Exception:
            log.exception("Visual tracker update failed")
            return None
        if not ok:
            return None
        box = BBox(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        if not self._sane(box, self._target.bbox):
            return None

        dt = max(0.0, frame_ts - self._target.last_seen_ts)
        self._motion.update(box, dt)
        self._target = TrackedTarget(
            target_id=self._target.target_id, bbox=box, confidence=1.0,
            class_id=self._target.class_id, class_name=self._target.class_name,
            last_seen_ts=frame_ts, velocity_px_s=self._motion.velocity,
            smooth_bbox=self._motion.smooth_bbox,
        )
        return self._target

    def reset(self) -> None:
        self._cv_tracker = None
        self._target = None
        self._motion = None
