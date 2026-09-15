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


class DistanceSource:
    def read(self) -> Optional[float]:
        raise NotImplementedError


class RangefinderSource(DistanceSource):
    """Optional authoritative distance source (e.g. TFmini-S over UART/I2C).

    Guarded: only usable once the rangefinder hardware addition (flagged in
    the plan, M4) is confirmed and wired. Not required for the vision-only
    baseline to function.
    """

    def __init__(self, port: str) -> None:
        raise NotImplementedError(
            "RangefinderSource requires the optional rangefinder hardware and its "
            "driver to be selected first - see docs plan M4 open item."
        )

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

    def estimate(self, detection: Detection) -> tuple[Optional[float], str]:
        rf = self.rangefinder.read()
        if rf is not None:
            return rf, "rangefinder"
        vision = estimate_distance_pinhole_m(detection, self.intrinsics)
        return vision, "vision"
