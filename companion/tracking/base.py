from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from companion.vision.detector import BBox, Detection


@dataclass
class TrackedTarget:
    target_id: int
    bbox: BBox
    confidence: float
    class_id: int
    class_name: str
    last_seen_ts: float
    velocity_px_s: tuple[float, float] = (0.0, 0.0)
    # Motion-filtered box (tracking/motion.py) - `bbox` stays the raw
    # detection so the app overlay shows exactly what the detector saw;
    # guidance and distance estimation read `guidance_bbox` instead, since
    # raw per-frame detector jitter turns directly into velocity-command
    # jitter otherwise.
    smooth_bbox: Optional[BBox] = None

    @property
    def guidance_bbox(self) -> BBox:
        return self.smooth_bbox if self.smooth_bbox is not None else self.bbox


class Tracker:
    """Abstraction so the tracking algorithm can be swapped without touching
    target selection, guidance, or safety code (per project requirement)."""

    def init_target(self, frame_ts: float, detection: Detection, target_id: int) -> TrackedTarget:
        raise NotImplementedError

    def update(self, frame_ts: float, detections: list[Detection]) -> Optional[TrackedTarget]:
        """Returns the updated TrackedTarget, or None if no matching detection
        was found this frame (caller decides REACQUIRE vs TARGET_LOST)."""
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError
