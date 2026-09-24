from __future__ import annotations

from typing import Optional

from companion.tracking.base import Tracker, TrackedTarget
from companion.tracking.motion import MotionModel, best_match_any
from companion.vision.detector import Detection


class ByteTrackTracker(Tracker):
    """Single-target adaptation of ByteTrack's own core idea (Zhang et al.,
    2022): don't throw away low-confidence detection boxes before trying to
    associate them - a real object that's briefly occluded, motion-blurred,
    or at a bad angle often still produces a real box, just a lower-scoring
    one, and a detector-level confidence cutoff (this project's
    `camera.score_threshold`, see hardware.yaml) would otherwise make that
    box invisible to tracking entirely, right when tracking needs it most.

    This is a from-scratch implementation of that two-stage association
    idea against this project's own `Tracker` interface, not a wrapper
    around ByteTrack's own reference repo or a `pip install bytetrack`
    package - deliberately, since ByteTrack's reference implementation
    isn't a single pinned package (most forks bundle a full YOLOX detection
    pipeline, torch and all, none of which this project needs - detection
    already happens on-sensor via the IMX500, see M2). The actual
    contribution IouKalmanTracker doesn't have is the two-stage match
    below; constant-velocity prediction and single-target bookkeeping are
    otherwise the same approach as IouKalmanTracker.

    Stage 1 matches the predicted bbox against detections at or above
    `high_score_thresh` (same IoU-based matching IouKalmanTracker always
    does). Only if that finds nothing does stage 2 retry against the
    "byte" detections - the confidence band between `low_score_thresh` and
    `high_score_thresh` that a detector-level score_threshold would
    normally have discarded before anything downstream ever saw them.
    Requires the caller to actually pass those low-confidence detections
    through in the first place; if the detector already filters everything
    below `high_score_thresh` (or below `min_score_threshold`) before this
    tracker sees it, stage 2 never has anything to match - this only helps
    if `camera.score_threshold` is at or below `low_score_thresh`.
    """

    def __init__(
        self,
        high_score_thresh: float = 0.6,
        low_score_thresh: float = 0.1,
        min_iou: float = 0.3,
    ) -> None:
        assert 0.0 <= low_score_thresh <= high_score_thresh <= 1.0
        self.high_score_thresh = high_score_thresh
        self.low_score_thresh = low_score_thresh
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
        class_id = self._target.class_id

        high = [d for d in detections if d.score >= self.high_score_thresh]
        best_det, _iou = best_match_any(predicted, high, class_id, self.min_iou)

        if best_det is None:
            # Stage 2 (the actual "Byte" in ByteTrack): retry against the
            # detections a confidence-only cutoff would have discarded,
            # before giving up on this frame entirely.
            low = [d for d in detections if self.low_score_thresh <= d.score < self.high_score_thresh]
            best_det, _iou = best_match_any(predicted, low, class_id, self.min_iou)

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
