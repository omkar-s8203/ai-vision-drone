from __future__ import annotations

import math
from typing import Optional, Sequence

from companion.vision.detector import BBox, Detection


class MotionModel:
    """Constant-velocity alpha-beta filter on the box center, plus an
    exponential average on its size.

    The trackers previously took velocity as a raw finite difference
    between two consecutive detections - one jittery detector box (a few
    pixels either way, routine for on-sensor detection) divided by a small
    frame gap becomes a huge, wrong velocity, which then wrecked the next
    frame's predicted box and, through it, the IoU match. Filtering
    velocity, bounding it relative to the target's own size, and capping how
    far a prediction may coast keeps prediction stable.
    """

    def __init__(
        self,
        bbox: BBox,
        alpha: float = 0.7,
        beta: float = 0.3,
        size_alpha: float = 0.5,
        max_coast_s: float = 0.5,
        max_speed_sizes_per_s: float = 10.0,
    ) -> None:
        self.alpha = alpha
        self.beta = beta
        self.size_alpha = size_alpha
        self.max_coast_s = max_coast_s
        self.max_speed_sizes_per_s = max_speed_sizes_per_s
        self.cx = bbox.cx
        self.cy = bbox.cy
        self.w = bbox.w
        self.h = bbox.h
        self.vx = 0.0
        self.vy = 0.0

    @property
    def smooth_bbox(self) -> BBox:
        return BBox(self.cx - self.w / 2, self.cy - self.h / 2, self.w, self.h)

    @property
    def velocity(self) -> tuple[float, float]:
        return (self.vx, self.vy)

    def predict(self, dt: float) -> BBox:
        """Where the target should be `dt` seconds after the last update.
        `dt` is capped at `max_coast_s`: a target unseen for a couple of
        seconds has no trustworthy velocity to extrapolate with, and
        projecting it the full gap sent the predicted box far from where
        the target actually reappears."""
        t = min(max(0.0, dt), self.max_coast_s)
        cx = self.cx + self.vx * t
        cy = self.cy + self.vy * t
        return BBox(cx - self.w / 2, cy - self.h / 2, self.w, self.h)

    def search_boxes(self, dt: float) -> list[BBox]:
        """Boxes to associate detections against: the motion prediction and,
        once the target has been unseen for a moment, also where it was last
        seen. A target that vanished behind an obstacle either kept walking
        (the prediction) or stopped there (the last position) - matching
        against only the extrapolation made the second case unrecoverable
        by IoU."""
        boxes = [self.predict(dt)]
        if dt > self.max_coast_s / 2:
            boxes.append(self.smooth_bbox)
        return boxes

    def update(self, measured: BBox, dt: float) -> None:
        if dt <= 0:
            # Same-timestamp duplicate: no time has passed to derive a
            # velocity from, so just blend the position in.
            self.cx += self.alpha * (measured.cx - self.cx)
            self.cy += self.alpha * (measured.cy - self.cy)
        else:
            t = min(dt, self.max_coast_s)
            pred_cx = self.cx + self.vx * t
            pred_cy = self.cy + self.vy * t
            rx = measured.cx - pred_cx
            ry = measured.cy - pred_cy
            self.cx = pred_cx + self.alpha * rx
            self.cy = pred_cy + self.alpha * ry
            self.vx += self.beta * rx / dt
            self.vy += self.beta * ry / dt
            limit = self.max_speed_sizes_per_s * max(self.w, self.h, 1.0)
            speed = math.hypot(self.vx, self.vy)
            if speed > limit:
                self.vx *= limit / speed
                self.vy *= limit / speed
        self.w += self.size_alpha * (measured.w - self.w)
        self.h += self.size_alpha * (measured.h - self.h)


def best_match(
    predicted: BBox,
    candidates: Sequence[Detection],
    class_id: int,
    min_iou: float,
    tie_margin: float = 0.1,
) -> tuple[Optional[Detection], float]:
    """Best same-class IoU match against the predicted box. When two
    candidates score within `tie_margin` of each other (two people crossing
    paths), IoU alone is close to a coin flip, so the one whose center is
    nearer the prediction wins - the closer of two near-equal overlaps is
    much more likely to be the same person than the further one."""
    scored: list[tuple[float, float, Detection]] = []
    for det in candidates:
        if det.class_id != class_id:
            continue
        iou = predicted.iou(det.bbox)
        if iou <= 0.0:
            continue
        dist = math.hypot(det.bbox.cx - predicted.cx, det.bbox.cy - predicted.cy)
        scored.append((iou, dist, det))
    if not scored:
        return None, 0.0
    top_iou = max(s[0] for s in scored)
    if top_iou < min_iou:
        return None, top_iou
    contenders = [s for s in scored if top_iou - s[0] <= tie_margin and s[0] >= min_iou]
    chosen = min(contenders, key=lambda s: s[1])
    return chosen[2], chosen[0]


def best_match_any(
    predicted_boxes: Sequence[BBox],
    candidates: Sequence[Detection],
    class_id: int,
    min_iou: float,
) -> tuple[Optional[Detection], float]:
    """best_match() against several hypotheses (see MotionModel.search_boxes);
    the hypothesis giving the strongest overlap wins."""
    best: tuple[Optional[Detection], float] = (None, 0.0)
    for box in predicted_boxes:
        det, iou = best_match(box, candidates, class_id, min_iou)
        if det is not None and iou > best[1]:
            best = (det, iou)
    return best
