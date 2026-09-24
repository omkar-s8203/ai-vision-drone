from __future__ import annotations

from typing import Optional

from companion.tracking.base import Tracker, TrackedTarget
from companion.tracking.motion import MotionModel, best_match_any
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
        self._motion: Optional[MotionModel] = None

    def init_target(self, frame_ts: float, detection: Detection, target_id: int) -> TrackedTarget:
        self._motion = MotionModel(detection.bbox)
        self._target = TrackedTarget(
            target_id=target_id,
            bbox=detection.bbox,
            confidence=detection.score,
            class_id=detection.class_id,
            class_name=detection.class_name,
            last_seen_ts=frame_ts,
            velocity_px_s=(0.0, 0.0),
            smooth_bbox=detection.bbox,
        )
        return self._target

    def update(self, frame_ts: float, detections: list[Detection]) -> Optional[TrackedTarget]:
        if self._target is None or self._motion is None or not detections:
            return None

        dt = max(0.0, frame_ts - self._target.last_seen_ts)
        predicted = self._motion.search_boxes(dt)

        best_det, _iou = best_match_any(predicted, detections, self._target.class_id, self.min_iou)
        if best_det is None:
            return None

        self._motion.update(best_det.bbox, dt)
        self._target = TrackedTarget(
            target_id=self._target.target_id,
            bbox=best_det.bbox,
            confidence=best_det.score,
            class_id=best_det.class_id,
            class_name=best_det.class_name,
            last_seen_ts=frame_ts,
            velocity_px_s=self._motion.velocity,
            smooth_bbox=self._motion.smooth_bbox,
        )
        return self._target

    def reset(self) -> None:
        self._target = None
        self._motion = None
