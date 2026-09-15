from __future__ import annotations

from typing import Optional

from companion.tracking.base import Tracker, TrackedTarget
from companion.vision.detector import Detection


class IouKalmanTracker(Tracker):
    """Default single-target tracker: IoU association against the active
    target's predicted bbox (constant-velocity prediction), no external
    tracking-library dependency. Swappable via the Tracker abstraction -
    see bytetrack_impl.py for the multi-object alternative.
    """

    def __init__(self, min_iou: float = 0.3) -> None:
        self.min_iou = min_iou
        self._target: Optional[TrackedTarget] = None

    def init_target(self, frame_ts: float, detection: Detection, target_id: int) -> TrackedTarget:
        self._target = TrackedTarget(
            target_id=target_id,
            bbox=detection.bbox,
            confidence=detection.score,
            class_id=detection.class_id,
            class_name=detection.class_name,
            last_seen_ts=frame_ts,
            velocity_px_s=(0.0, 0.0),
        )
        return self._target

    def _predicted_bbox(self, dt: float):
        assert self._target is not None
        b = self._target.bbox
        vx, vy = self._target.velocity_px_s
        from companion.vision.detector import BBox

        return BBox(x=b.x + vx * dt, y=b.y + vy * dt, w=b.w, h=b.h)

    def update(self, frame_ts: float, detections: list[Detection]) -> Optional[TrackedTarget]:
        if self._target is None or not detections:
            return None

        dt = max(0.0, frame_ts - self._target.last_seen_ts)
        predicted = self._predicted_bbox(dt)

        best_det: Optional[Detection] = None
        best_iou = 0.0
        for det in detections:
            if det.class_id != self._target.class_id:
                continue
            iou = predicted.iou(det.bbox)
            if iou > best_iou:
                best_iou = iou
                best_det = det

        if best_det is None or best_iou < self.min_iou:
            return None

        old_bbox = self._target.bbox
        vx = (best_det.bbox.cx - old_bbox.cx) / dt if dt > 0 else 0.0
        vy = (best_det.bbox.cy - old_bbox.cy) / dt if dt > 0 else 0.0

        self._target = TrackedTarget(
            target_id=self._target.target_id,
            bbox=best_det.bbox,
            confidence=best_det.score,
            class_id=best_det.class_id,
            class_name=best_det.class_name,
            last_seen_ts=frame_ts,
            velocity_px_s=(vx, vy),
        )
        return self._target

    def reset(self) -> None:
        self._target = None
