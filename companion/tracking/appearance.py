from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from companion.tracking.base import TrackedTarget
from companion.vision.detector import BBox, Detection


@dataclass(frozen=True)
class AppearanceSignature:
    """A lightweight visual "memory" of a target - a normalized HSV color
    histogram of its cropped bounding box, not a deep-learning embedding
    (this project's IMX500 pipeline only runs its one fixed on-sensor
    detection model, not arbitrary per-crop inference). Cheap to compute
    and compare, and good enough to tell "the person I selected" apart from
    a different person in a different colored shirt - which is the actual
    job here, not general re-identification research."""

    class_id: int
    histogram: np.ndarray


def _crop(frame_bgr: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
    height, width = frame_bgr.shape[:2]
    x0 = max(0, int(bbox.x))
    y0 = max(0, int(bbox.y))
    x1 = min(width, int(bbox.x + bbox.w))
    y1 = min(height, int(bbox.y + bbox.h))
    if x1 <= x0 or y1 <= y0:
        return None
    return frame_bgr[y0:y1, x0:x1]


def compute_signature(frame_bgr: Optional[np.ndarray], bbox: BBox, class_id: int) -> Optional[AppearanceSignature]:
    """Returns None if there's no real frame to sample from (sim mode has
    no pixel data) or the bbox doesn't land inside the frame - callers must
    treat that as "can't learn/match right now", not an error."""
    if frame_bgr is None:
        return None
    import cv2  # lazy import: only needed once real frames are involved

    crop = _crop(frame_bgr, bbox)
    if crop is None or crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    cv2.normalize(histogram, histogram, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return AppearanceSignature(class_id=class_id, histogram=histogram)


def similarity(a: AppearanceSignature, b: AppearanceSignature) -> float:
    """1.0 = identical color distribution, ~0 = unrelated, negative =
    anti-correlated. cv2.HISTCMP_CORREL is a standard, fast histogram
    similarity metric - no ML inference involved."""
    import cv2

    return float(cv2.compareHist(a.histogram, b.histogram, cv2.HISTCMP_CORREL))


class AppearanceMemory:
    """Remembers the currently/most-recently selected target's appearance
    so it can be auto-reacquired after a full TARGET_LOST (the tracker's
    own short-lived REACQUIRE window is motion/IoU-based and independent of
    this - see companion/tracking/state.py). Single-slot by design: this
    project tracks one target at a time, so there's only ever one thing to
    remember. A no-op wherever no real frame is available (sim mode).
    """

    def __init__(self, min_similarity: float = 0.65, min_margin: float = 0.08) -> None:
        self.min_similarity = min_similarity
        # A real field-reported bug: with no margin check, find_match()
        # always picked whichever same-class candidate scored highest, even
        # when a second candidate scored almost as well - e.g. two people
        # in similarly-colored clothing. Once the original target left
        # frame, this could silently relock onto the WRONG person with no
        # sign anything had gone wrong (same tracking_state, same "target
        # locked" UI). min_margin requires the best candidate to clearly
        # beat the second-best (not just clear min_similarity) before
        # trusting a match - a starting, deliberately conservative value,
        # not yet tuned against real multi-person footage (same honesty
        # this project already applies to camera.score_threshold - see
        # hardware.yaml).
        self.min_margin = min_margin
        self._signature: Optional[AppearanceSignature] = None

    @property
    def has_signature(self) -> bool:
        return self._signature is not None

    def learn(self, frame_bgr: Optional[np.ndarray], target: TrackedTarget) -> None:
        signature = compute_signature(frame_bgr, target.bbox, target.class_id)
        if signature is not None:
            self._signature = signature

    def forget(self) -> None:
        self._signature = None

    def find_match(self, frame_bgr: Optional[np.ndarray], detections: list[Detection]) -> Optional[Detection]:
        """Returns the best same-class detection whose appearance most
        closely matches the remembered signature, if any clears
        min_similarity AND clearly beats every other same-class candidate
        by at least min_margin - else None (refuses to guess rather than
        pick between two ambiguous candidates, e.g. two people in
        similarly-colored clothing - see min_margin's own docstring for the
        real bug this fixes). Callers should re-`learn()` from the match
        once tracking resumes, so the remembered signature adapts to the
        target's current appearance rather than staying frozen from the
        moment it was first selected."""
        if self._signature is None or frame_bgr is None:
            return None

        scored: list[tuple[float, Detection]] = []
        for detection in detections:
            if detection.class_id != self._signature.class_id:
                continue
            candidate = compute_signature(frame_bgr, detection.bbox, detection.class_id)
            if candidate is None:
                continue
            score = similarity(self._signature, candidate)
            if score >= self.min_similarity:
                scored.append((score, detection))

        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best_detection = scored[0]
        if len(scored) > 1 and best_score - scored[1][0] < self.min_margin:
            return None
        return best_detection
