from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from companion.guidance.distance import DistanceEstimator
from companion.vision.detector import Detection


@dataclass(frozen=True)
class ObstacleAlert:
    class_name: str
    distance_m: float


def check_proximity(
    detections: list[Detection],
    distance_estimator: DistanceEstimator,
    min_safe_distance_m: float,
) -> Optional[ObstacleAlert]:
    """Returns the closest obstacle if anything currently detected is nearer
    than `min_safe_distance_m`, else None.

    Checks every detection on the frame, not just the tracked target - an
    untracked obstacle closing in (e.g. a wall, a second person) is just as
    dangerous as the followed subject getting too close, and the Follow/
    Orbit controllers only ever reason about the one target they're
    tracking. This is a separate, cross-mode check the Safety Supervisor
    applies on top of whatever guidance controller is active.
    """
    closest: Optional[ObstacleAlert] = None
    for det in detections:
        distance_m, _source = distance_estimator.estimate(det)
        if distance_m is None or distance_m >= min_safe_distance_m:
            continue
        if closest is None or distance_m < closest.distance_m:
            closest = ObstacleAlert(class_name=det.class_name, distance_m=distance_m)
    return closest
