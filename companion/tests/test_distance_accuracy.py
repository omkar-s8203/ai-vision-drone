import pytest

from companion.guidance.distance import (
    CameraIntrinsics,
    DistanceEstimator,
    DistanceFilter,
    estimate_distance_vision_m,
)
from companion.vision.detector import BBox, Detection

INTRINSICS = CameraIntrinsics(image_width=1280, image_height=720, fx=900.0, fy=900.0, cx=640.0, cy=360.0)


def person(x, y, w, h):
    return Detection(bbox=BBox(x, y, w, h), score=0.9, class_id=0, class_name="person", frame_ts=0.0)


def car(x, y, w, h):
    return Detection(bbox=BBox(x, y, w, h), score=0.9, class_id=2, class_name="car", frame_ts=0.0)


def test_upright_person_distance_uses_height_when_preferred():
    # 1.7m * 900 / 153px = 10.0m
    det = person(500, 200, 60, 153)
    assert estimate_distance_vision_m(det, INTRINSICS, prefer_height=True) == pytest.approx(10.0)


def test_person_distance_is_steady_across_pose_when_using_height():
    """Same person at the same distance, box width swinging with pose."""
    front_on = person(500, 200, 60, 153)
    side_on = person(500, 200, 30, 153)
    a = estimate_distance_vision_m(front_on, INTRINSICS, prefer_height=True)
    b = estimate_distance_vision_m(side_on, INTRINSICS, prefer_height=True)
    assert a == pytest.approx(b)
    # ...whereas the width-only estimate swings 2x with the same pose change.
    wa = estimate_distance_vision_m(front_on, INTRINSICS)
    wb = estimate_distance_vision_m(side_on, INTRINSICS)
    assert wb / wa == pytest.approx(2.0)


def test_default_stays_width_based_for_the_conservative_proximity_check():
    det = person(500, 200, 45, 153)
    assert estimate_distance_vision_m(det, INTRINSICS) == pytest.approx(0.5 * 900 / 45)


def test_non_upright_person_falls_back_to_width():
    crouching = person(500, 400, 100, 90)
    assert estimate_distance_vision_m(crouching, INTRINSICS, prefer_height=True) == pytest.approx(0.5 * 900 / 100)


def test_other_classes_keep_using_width():
    det = car(300, 300, 180, 100)
    assert estimate_distance_vision_m(det, INTRINSICS, prefer_height=True) == pytest.approx(1.8 * 900 / 180)


def test_clipped_person_falls_back_to_intact_width():
    feet_cut_off = person(500, 600, 60, 120)  # y+h == 720 == image bottom
    d = estimate_distance_vision_m(feet_cut_off, INTRINSICS, reject_truncated=True, prefer_height=True)
    assert d == pytest.approx(0.5 * 900 / 60)


def test_clipped_in_both_dimensions_is_unknown_not_a_guess():
    corner = person(1230, 620, 50, 100)  # touches right and bottom edges
    assert estimate_distance_vision_m(corner, INTRINSICS, reject_truncated=True, prefer_height=True) is None


def test_clipped_car_is_unknown_when_rejecting_truncation():
    clipped = car(1100, 300, 180, 100)  # x+w == 1280
    assert estimate_distance_vision_m(clipped, INTRINSICS, reject_truncated=True) is None
    assert estimate_distance_vision_m(clipped, INTRINSICS) is not None  # proximity keeps its old behavior


def test_truncation_only_matters_when_asked_for():
    corner = person(1230, 620, 50, 100)
    assert estimate_distance_vision_m(corner, INTRINSICS) is not None


def test_estimator_passes_the_new_options_through():
    estimator = DistanceEstimator(INTRINSICS)
    det = person(500, 200, 60, 153)
    distance, source = estimator.estimate(det, prefer_height=True)
    assert distance == pytest.approx(10.0)
    assert source == "vision"


# --- DistanceFilter ---------------------------------------------------------

def test_filter_rejects_a_single_outlier_frame():
    f = DistanceFilter()
    for i in range(5):
        out = f.update(6.0, ts=0.1 * i)
    spike = f.update(20.0, ts=0.5)
    assert out == pytest.approx(6.0)
    assert spike == pytest.approx(6.0)  # median of (6, 6, 20) is 6


def test_filter_follows_a_genuine_sustained_change():
    f = DistanceFilter()
    for i in range(5):
        f.update(6.0, ts=0.1 * i)
    out = None
    for i in range(5, 30):
        out = f.update(10.0, ts=0.1 * i)
    assert out == pytest.approx(10.0, abs=0.1)


def test_filter_smooths_jitter():
    f = DistanceFilter()
    outs = [f.update(6.0 + (0.6 if i % 2 else -0.6), ts=0.1 * i) for i in range(40)]
    assert max(outs[10:]) - min(outs[10:]) < 1.2


def test_filter_does_not_blend_a_stale_history_after_a_gap():
    f = DistanceFilter(max_age_s=1.0)
    for i in range(5):
        f.update(6.0, ts=0.1 * i)
    assert f.update(12.0, ts=5.0) == pytest.approx(12.0)


def test_filter_passes_unknown_distance_through_as_unknown():
    f = DistanceFilter()
    f.update(6.0, ts=0.0)
    assert f.update(None, ts=0.1) is None


def test_filter_reset_forgets_everything():
    f = DistanceFilter()
    f.update(6.0, ts=0.0)
    f.reset()
    assert f.update(15.0, ts=0.1) == pytest.approx(15.0)
