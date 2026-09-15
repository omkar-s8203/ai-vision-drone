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
