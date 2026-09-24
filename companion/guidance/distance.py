from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from companion.vision.detector import Detection

# Average real-world object width in meters, used for the monocular pinhole
# estimate. Coarse by nature - see docs/plan M4 for why this is a fallback,
# not the authoritative source once a rangefinder is available.
KNOWN_OBJECT_WIDTHS_M: dict[str, float] = {
    "person": 0.5,
    "car": 1.8,
    "truck": 2.3,
    "bicycle": 0.6,
    "motorcycle": 0.8,
}

# Real-world heights for classes where height is a steadier cue than width.
# A standing person's box width swings by 2-3x with pose and facing (front-on
# vs side-on, arms out, mid-stride) while their height barely changes, so
# width-only estimates made the distance - and through it Follow's forward/
# back velocity - wobble with every step.
KNOWN_OBJECT_HEIGHTS_M: dict[str, float] = {
    "person": 1.7,
}

# Box height/width above which a person is treated as upright (standing or
# walking). A crouching, sitting or lying person's height no longer reflects
# their real size, so those fall back to the width estimate.
UPRIGHT_MIN_ASPECT = 1.2

# Pixels from an image border within which a box counts as clipped by it.
EDGE_MARGIN_PX = 2.0


@dataclass(frozen=True)
class CameraIntrinsics:
    image_width: int
    image_height: int
    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def from_dict(cls, d: dict) -> "CameraIntrinsics":
        return cls(
            image_width=int(d["image_width"]),
            image_height=int(d["image_height"]),
            fx=float(d["fx"]),
            fy=float(d["fy"]),
            cx=float(d["cx"]),
            cy=float(d["cy"]),
        )


def estimate_distance_pinhole_m(
    detection: Detection, intrinsics: CameraIntrinsics
) -> Optional[float]:
    """distance = (real_world_width * focal_length_px) / apparent_width_px."""
    real_width = KNOWN_OBJECT_WIDTHS_M.get(detection.class_name)
    if real_width is None or detection.bbox.w <= 0:
        return None
    return (real_width * intrinsics.fx) / detection.bbox.w


def _touches_horizontal_edges(bbox, intrinsics: CameraIntrinsics) -> bool:
    return bbox.x <= EDGE_MARGIN_PX or bbox.x + bbox.w >= intrinsics.image_width - EDGE_MARGIN_PX


def _touches_vertical_edges(bbox, intrinsics: CameraIntrinsics) -> bool:
    return bbox.y <= EDGE_MARGIN_PX or bbox.y + bbox.h >= intrinsics.image_height - EDGE_MARGIN_PX


def _estimate_custom_object_m(
    detection: Detection,
    intrinsics: CameraIntrinsics,
    size_m: tuple[Optional[float], Optional[float]],
    reject_truncated: bool,
    prefer_height: bool,
) -> Optional[float]:
    """Distance to a taught object from the real size the operator supplied. Uses
    whichever dimension is known (height first when preferred), skipping one that is
    clipped by the image border when truncation is being rejected."""
    width_m, height_m = size_m
    bbox = detection.bbox
    candidates = []
    if height_m is not None:
        candidates.append((height_m * intrinsics.fy / bbox.h, _touches_vertical_edges(bbox, intrinsics)))
    if width_m is not None:
        candidates.append((width_m * intrinsics.fx / bbox.w, _touches_horizontal_edges(bbox, intrinsics)))
    if not prefer_height:
        candidates.reverse()
    for distance, clipped in candidates:
        if not (reject_truncated and clipped):
            return distance
    return None


def estimate_distance_vision_m(
    detection: Detection,
    intrinsics: CameraIntrinsics,
    reject_truncated: bool = False,
    prefer_height: bool = False,
    custom_sizes: Optional[dict] = None,
) -> Optional[float]:
    """Monocular estimate. With `prefer_height`, an upright person's height
    is used instead of their (pose-dependent) width - meant for Follow/Orbit,
    which want a steady number. Obstacle proximity deliberately keeps the
    default width-only estimate: it is the more conservative one for a
    "something is too close" safety check (arms out or side-on reads closer,
    never further). With `reject_truncated`, a
    box clipped by the image border in the dimension being measured is
    refused - a clipped box is smaller than the real object, so the
    estimate would read as further away than the target really is, and
    Follow would close in on it. The other dimension is used instead if it
    is intact, else None (Follow holds its forward speed at zero on an
    unknown distance rather than guessing).
    """
    bbox = detection.bbox
    if bbox.w <= 0 or bbox.h <= 0:
        return None

    if custom_sizes and detection.class_name in custom_sizes:
        return _estimate_custom_object_m(
            detection, intrinsics, custom_sizes[detection.class_name], reject_truncated, prefer_height
        )

    real_height = KNOWN_OBJECT_HEIGHTS_M.get(detection.class_name)
    if prefer_height and real_height is not None and bbox.h >= UPRIGHT_MIN_ASPECT * bbox.w:
        if not (reject_truncated and _touches_vertical_edges(bbox, intrinsics)):
            return (real_height * intrinsics.fy) / bbox.h

    if reject_truncated and _touches_horizontal_edges(bbox, intrinsics):
        return None
    return estimate_distance_pinhole_m(detection, intrinsics)


class DistanceFilter:
    """Median-of-three then exponential smoothing of the followed target's
    distance. Detector box size jitters frame to frame, and one bad box
    (a partial occlusion, a merged detection) used to become a one-frame
    forward/back velocity spike; the median rejects a lone outlier and the
    smoothing takes the remaining noise off. Samples older than
    `max_age_s` are discarded so a stale history never blends into a fresh
    estimate after a gap.
    """

    def __init__(self, alpha: float = 0.5, max_age_s: float = 1.0) -> None:
        self.alpha = alpha
        self.max_age_s = max_age_s
        self._samples: list[tuple[float, float]] = []
        self._smoothed: Optional[float] = None
        self._smoothed_ts = 0.0

    def reset(self) -> None:
        self._samples.clear()
        self._smoothed = None

    def update(self, distance_m: Optional[float], ts: float) -> Optional[float]:
        if distance_m is None:
            return None
        self._samples = [(t, d) for t, d in self._samples if ts - t <= self.max_age_s]
        self._samples.append((ts, distance_m))
        self._samples = self._samples[-3:]
        median = sorted(d for _, d in self._samples)[len(self._samples) // 2]
        if self._smoothed is None or ts - self._smoothed_ts > self.max_age_s:
            self._smoothed = median
        else:
            self._smoothed += self.alpha * (median - self._smoothed)
        self._smoothed_ts = ts
        return self._smoothed


class DistanceSource:
    def read(self) -> Optional[float]:
        raise NotImplementedError


class NullDistanceSource(DistanceSource):
    def read(self) -> Optional[float]:
        return None


class DistanceEstimator:
    """Combines an authoritative source (if present) with the vision fallback.

    Rangefinder wins when it has a fresh reading; vision estimate is used
    otherwise, per the plan's fallback design. A physical safety boundary
    (approach-test) should not be gated on the vision-only path alone -
    the approach-test controller enforces that separately.
    """

    def __init__(
        self,
        intrinsics: CameraIntrinsics,
        rangefinder: Optional[DistanceSource] = None,
    ) -> None:
        self.intrinsics = intrinsics
        self.rangefinder = rangefinder or NullDistanceSource()
        # Objects the operator taught (companion/learning): name -> (width_m, height_m),
        # either may be None. Without a real size a taught object has NO distance
        # estimate (never a guess), and Follow then holds its forward speed at zero.
        self.custom_sizes: dict[str, tuple[Optional[float], Optional[float]]] = {}

    def register_custom_object(
        self, name: str, width_m: Optional[float], height_m: Optional[float]
    ) -> None:
        if width_m is None and height_m is None:
            self.custom_sizes.pop(name, None)
        else:
            self.custom_sizes[name] = (width_m, height_m)

    def estimate(
        self,
        detection: Detection,
        trust_rangefinder: bool = False,
        reject_truncated: bool = False,
        prefer_height: bool = False,
    ) -> tuple[Optional[float], str]:
        """`trust_rangefinder` must only be set for the detection actually
        matching the tracker's current target - a forward-facing rangefinder
        gives one boresight reading per frame, not a per-object one, so
        applying it to *every* detection in frame (the previous, unreachable-
        in-practice default) would report the tracked target's own distance
        for unrelated objects too, silently defeating the obstacle-proximity
        check for anything not being tracked (see docs/safety-case.md).
        Defaults to vision-only, the safe choice when the caller doesn't
        know or care whether this is the tracked target."""
        if trust_rangefinder:
            rf = self.rangefinder.read()
            if rf is not None:
                return rf, "rangefinder"
        vision = estimate_distance_vision_m(
            detection, self.intrinsics, reject_truncated=reject_truncated, prefer_height=prefer_height,
            custom_sizes=self.custom_sizes,
        )
        return vision, "vision"
