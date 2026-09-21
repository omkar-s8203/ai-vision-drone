from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from companion.guidance.distance import DistanceEstimator
from companion.vision.detector import Detection


@dataclass(frozen=True)
class ObstacleAlert:
    class_name: str
    distance_m: float


_TRACKED_TARGET_IOU_THRESHOLD = 0.5


def check_proximity(
    detections: list[Detection],
    distance_estimator: DistanceEstimator,
    min_safe_distance_m: float,
    tracked_target: Optional[Detection] = None,
) -> Optional[ObstacleAlert]:
    """Returns the closest obstacle if anything currently detected is nearer
    than `min_safe_distance_m`, else None.

    Checks every detection on the frame, not just the tracked target - an
    untracked obstacle closing in (e.g. a wall, a second person) is just as
    dangerous as the followed subject getting too close, and the Follow/
    Orbit controllers only ever reason about the one target they're
    tracking. This is a separate, cross-mode check the Safety Supervisor
    applies on top of whatever guidance controller is active.

    `tracked_target` (the same synthesized Detection process_frame() already
    builds from the tracker's current target, if any) is matched against
    each candidate by class + IoU, not object identity - a fresh per-frame
    Detection never equals the tracker's own stored one even when it's
    clearly the same object. Only the match, if any, is allowed to trust a
    rangefinder reading (DistanceEstimator.estimate's `trust_rangefinder`) -
    everything else always falls back to the vision estimate, so a single
    boresight rangefinder reading never gets misapplied to an unrelated
    object's distance (see docs/safety-case.md).
    """
    closest: Optional[ObstacleAlert] = None
    for det in detections:
        is_tracked_target = (
            tracked_target is not None
            and det.class_name == tracked_target.class_name
            and det.bbox.iou(tracked_target.bbox) >= _TRACKED_TARGET_IOU_THRESHOLD
        )
        distance_m, _source = distance_estimator.estimate(det, trust_rangefinder=is_tracked_target)
        if distance_m is None or distance_m >= min_safe_distance_m:
            continue
        if closest is None or distance_m < closest.distance_m:
            closest = ObstacleAlert(class_name=det.class_name, distance_m=distance_m)
    return closest
