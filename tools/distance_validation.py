"""Validates the M4 monocular pinhole distance estimator against docs plan
M4's own measured-ground-truth acceptance test: place a target at known
distances (the plan's own example: 2m/5m/10m/20m) and compare the vision
estimate against the real, physically-measured distance.

This closes the *tooling* gap only - it still needs two things from real
hardware/a real environment before it produces the actual M4 numbers:
1. Real camera intrinsics from `tools/calibrate_camera.py` (not yet run -
   `camera_calibration.yaml` still holds placeholder values).
2. A real set of measurements: at each known distance, the bounding-box
   pixel width the detector actually reported for the test subject.

Usage - first generate a fillable template, then measure and fill it in:

    python tools/distance_validation.py --template > measurements.json
    # ... place the subject at each distance, record the detector's real
    # bbox width in pixels at that distance, fill measurements.json ...
    python tools/distance_validation.py measurements.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion.config.loader import load_yaml  # noqa: E402
from companion.guidance.distance import (  # noqa: E402
    KNOWN_OBJECT_WIDTHS_M,
    CameraIntrinsics,
    estimate_distance_pinhole_m,
)
from companion.vision.detector import BBox, Detection  # noqa: E402

# The plan's own vision-only accuracy target, and the range it applies to.
MAX_ERROR_PCT = 15.0
VALIDATED_RANGE_M = (3.0, 15.0)

TEMPLATE = [
    {"label": "2m", "class_name": "person", "actual_distance_m": 2.0, "bbox_w_px": None},
    {"label": "5m", "class_name": "person", "actual_distance_m": 5.0, "bbox_w_px": None},
    {"label": "10m", "class_name": "person", "actual_distance_m": 10.0, "bbox_w_px": None},
    {"label": "20m", "class_name": "person", "actual_distance_m": 20.0, "bbox_w_px": None},
]


@dataclass
class DistancePoint:
    label: str
    class_name: str
    actual_distance_m: float
    estimated_distance_m: float | None
    error_pct: float | None

    @property
    def in_validated_range(self) -> bool:
        lo, hi = VALIDATED_RANGE_M
        return lo <= self.actual_distance_m <= hi


@dataclass
class DistanceValidationReport:
    points: list

    @property
    def in_range_points(self) -> list:
        return [p for p in self.points if p.in_validated_range and p.error_pct is not None]

    @property
    def mean_error_pct(self) -> float | None:
        in_range = self.in_range_points
        if not in_range:
            return None
        return sum(p.error_pct for p in in_range) / len(in_range)

    def passes(self) -> bool:
        in_range = self.in_range_points
        return bool(in_range) and all(p.error_pct <= MAX_ERROR_PCT for p in in_range)

    def report(self) -> str:
        lines = ["label      class        actual_m  estimated_m  error_%"]
        for p in self.points:
            est = f"{p.estimated_distance_m:.2f}" if p.estimated_distance_m is not None else "n/a"
            err = f"{p.error_pct:.1f}" if p.error_pct is not None else "n/a"
            flag = "" if p.in_validated_range else "  (outside 3-15m validated range)"
            lines.append(
                f"{p.label:<10} {p.class_name:<12} {p.actual_distance_m:<9} {est:<12} {err}{flag}"
            )
        lo, hi = VALIDATED_RANGE_M
        if self.mean_error_pct is None:
            lines.append(f"\nNo points fall within the {lo:.0f}-{hi:.0f}m validated range.")
        else:
            status = "PASS" if self.passes() else "FAIL"
            lines.append(
                f"\nMean error within {lo:.0f}-{hi:.0f}m range: {self.mean_error_pct:.1f}% "
                f"(target < {MAX_ERROR_PCT:.0f}%) [{status}]"
            )
        return "\n".join(lines)


def validate(measurements: list, intrinsics: CameraIntrinsics) -> DistanceValidationReport:
    points = []
    for m in measurements:
        class_name = m["class_name"]
        bbox_w_px = m.get("bbox_w_px")
        actual = float(m["actual_distance_m"])
        if bbox_w_px is None or class_name not in KNOWN_OBJECT_WIDTHS_M:
            points.append(DistancePoint(m.get("label", "?"), class_name, actual, None, None))
            continue
        detection = Detection(
            bbox=BBox(0.0, 0.0, float(bbox_w_px), 0.0),
            score=1.0,
            class_id=0,
            class_name=class_name,
            frame_ts=0.0,
        )
        estimated = estimate_distance_pinhole_m(detection, intrinsics)
        error_pct = None if estimated is None else abs(estimated - actual) / actual * 100.0
        points.append(DistancePoint(m.get("label", "?"), class_name, actual, estimated, error_pct))
    return DistanceValidationReport(points=points)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", nargs="?", help="path to a filled-in measurements JSON file")
    parser.add_argument("--template", action="store_true", help="print a fillable measurements.json template and exit")
    args = parser.parse_args()

    if args.template:
        print(json.dumps(TEMPLATE, indent=2))
        return

    if not args.measurements:
        parser.error("pass a measurements JSON file, or --template to generate one")
        return

    intrinsics = CameraIntrinsics.from_dict(load_yaml("camera_calibration.yaml"))
    measurements = json.loads(Path(args.measurements).read_text())
    report = validate(measurements, intrinsics)
    print(report.report())
    sys.exit(0 if report.passes() else 1)


if __name__ == "__main__":
    main()
