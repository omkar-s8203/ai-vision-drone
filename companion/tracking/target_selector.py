from __future__ import annotations

from typing import Optional

from companion.vision.detector import BBox, Detection


def select_target(
    detections: list[Detection], selection_bbox: BBox, min_iou: float = 0.1
) -> Optional[Detection]:
    """Matches an operator's tap/drag selection to the closest current
    detection, so the tracker is initialized on a real detected object
    rather than the raw (possibly imprecise) touch rectangle."""
    best_det: Optional[Detection] = None
    best_iou = 0.0
    for det in detections:
        iou = selection_bbox.iou(det.bbox)
        if iou > best_iou:
            best_iou = iou
            best_det = det
    if best_det is None or best_iou < min_iou:
        return None
    return best_det


def select_target_at_point(detections: list[Detection], x: float, y: float) -> Optional[Detection]:
    """Tap-to-select: finds which detection's box contains the tap point,
    rather than matching by overlap against a drawn selection rectangle
    (IoU against a tiny tap-sized box would be misleadingly low even for a
    dead-center tap on a large object). When multiple boxes overlap the
    point, picks the smallest one - the most specific match, matching how
    people expect tapping a person standing in front of a car to select
    the person, not the car behind them."""
    best_det: Optional[Detection] = None
    best_area = None
    for det in detections:
        b = det.bbox
        if b.x <= x <= b.x + b.w and b.y <= y <= b.y + b.h:
            if best_area is None or b.area < best_area:
                best_area = b.area
                best_det = det
    return best_det
