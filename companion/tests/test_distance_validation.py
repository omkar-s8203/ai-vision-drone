"""Tests for tools/distance_validation.py - pure math over synthetic
intrinsics/measurements, no camera/hardware needed."""

import pytest

from companion.guidance.distance import CameraIntrinsics
from tools.distance_validation import MAX_ERROR_PCT, validate

INTRINSICS = CameraIntrinsics(image_width=1280, image_height=720, fx=1000.0, fy=1000.0, cx=640.0, cy=360.0)


def _bbox_w_for_exact_distance(class_width_m: float, distance_m: float, fx: float) -> float:
    """Inverts estimate_distance_pinhole_m's own formula so a synthetic
    measurement can assert a known, exact error."""
    return (class_width_m * fx) / distance_m


def test_validate_reports_zero_error_for_an_exact_match():
    bbox_w = _bbox_w_for_exact_distance(0.5, 5.0, INTRINSICS.fx)  # person width = 0.5m
    measurements = [{"label": "5m", "class_name": "person", "actual_distance_m": 5.0, "bbox_w_px": bbox_w}]
    report = validate(measurements, INTRINSICS)
    assert report.points[0].error_pct == pytest.approx(0.0, abs=1e-6)
    assert report.passes()


def test_validate_flags_a_large_error_as_a_failure():
    measurements = [
        {"label": "5m", "class_name": "person", "actual_distance_m": 5.0, "bbox_w_px": 50.0}
    ]  # implies ~10m estimate, ~100% error
    report = validate(measurements, INTRINSICS)
    assert report.points[0].error_pct > MAX_ERROR_PCT
    assert not report.passes()


def test_validate_only_averages_points_within_the_3_to_15m_range():
    in_range_bbox = _bbox_w_for_exact_distance(0.5, 10.0, INTRINSICS.fx)
    out_of_range_bbox = _bbox_w_for_exact_distance(0.5, 20.0, INTRINSICS.fx) * 2  # deliberately bad, but out of range
    measurements = [
        {"label": "10m", "class_name": "person", "actual_distance_m": 10.0, "bbox_w_px": in_range_bbox},
        {"label": "20m", "class_name": "person", "actual_distance_m": 20.0, "bbox_w_px": out_of_range_bbox},
    ]
    report = validate(measurements, INTRINSICS)
    assert report.mean_error_pct == pytest.approx(0.0, abs=1e-6)
    assert report.passes()  # the bad out-of-range point must not drag down the in-range verdict


def test_validate_handles_a_missing_bbox_measurement_without_crashing():
    measurements = [{"label": "5m", "class_name": "person", "actual_distance_m": 5.0, "bbox_w_px": None}]
    report = validate(measurements, INTRINSICS)
    assert report.points[0].estimated_distance_m is None
    assert report.mean_error_pct is None
    assert not report.passes()


def test_validate_handles_an_unknown_class_without_crashing():
    measurements = [{"label": "5m", "class_name": "airplane", "actual_distance_m": 5.0, "bbox_w_px": 100.0}]
    report = validate(measurements, INTRINSICS)
    assert report.points[0].estimated_distance_m is None


def test_report_renders_without_crashing_when_no_points_are_in_range():
    measurements = [{"label": "1m", "class_name": "person", "actual_distance_m": 1.0, "bbox_w_px": 500.0}]
    report = validate(measurements, INTRINSICS)
    assert "No points fall within" in report.report()
