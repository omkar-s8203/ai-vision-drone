from __future__ import annotations

from typing import Optional

from companion.tracking.base import Tracker, TrackedTarget
from companion.vision.detector import Detection


class ByteTrackTracker(Tracker):
    """Adapter slot for a ByteTrack-backed implementation.

    Not implemented by default: ByteTrack's reference implementation isn't a
    single pinned pip package, so wiring it in is a deliberate dependency
    decision, not something to fake. Install a ByteTrack package (e.g. the
    `yolox`-based reference or a maintained fork), then implement init_target/
    update here against IouKalmanTracker's interface - no other module needs
    to change, that's the point of the Tracker abstraction.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "ByteTrackTracker requires a ByteTrack dependency to be chosen and installed "
            "first. Use IouKalmanTracker (companion/tracking/iou_tracker.py) until then."
        )

    def init_target(self, frame_ts: float, detection: Detection, target_id: int) -> TrackedTarget:
        raise NotImplementedError

    def update(self, frame_ts: float, detections: list[Detection]) -> Optional[TrackedTarget]:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError
