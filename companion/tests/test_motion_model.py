import math
import random

import pytest

from companion.tracking.bytetrack_impl import ByteTrackTracker
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.motion import MotionModel, best_match
from companion.vision.detector import BBox, Detection


def det(x, y, w=50, h=100, class_id=0, score=0.9, ts=0.0):
    return Detection(bbox=BBox(x, y, w, h), score=score, class_id=class_id, class_name="person", frame_ts=ts)


def test_velocity_converges_on_steady_motion():
    model = MotionModel(BBox(0, 0, 50, 100))
    for i in range(1, 30):
        model.update(BBox(10.0 * i, 0, 50, 100), dt=0.1)  # 100 px/s
    assert model.vx == pytest.approx(100.0, rel=0.05)
    assert model.vy == pytest.approx(0.0, abs=2.0)


def test_one_jittery_box_no_longer_creates_a_huge_velocity():
    """The old finite difference turned a 6px detector wobble over a 33ms
    frame gap into ~180 px/s of phantom velocity."""
    model = MotionModel(BBox(100, 100, 50, 100))
    model.update(BBox(106, 100, 50, 100), dt=0.033)
    assert abs(model.vx) < 100.0


def test_filtered_velocity_is_steadier_than_raw_finite_difference_under_jitter():
    rng = random.Random(7)
    model = MotionModel(BBox(0, 0, 50, 100))
    raw_prev = 0.0
    raw_speeds, filtered_speeds = [], []
    for i in range(1, 200):
        measured_x = 3.0 * i + rng.uniform(-5, 5)  # true speed: 3px/frame @ 30fps = 90 px/s
        raw_speeds.append((measured_x - raw_prev) / 0.033)
        raw_prev = measured_x
        model.update(BBox(measured_x, 0, 50, 100), dt=0.033)
        filtered_speeds.append(model.vx)
    def spread(values):
        tail = values[50:]
        mean = sum(tail) / len(tail)
        return math.sqrt(sum((v - mean) ** 2 for v in tail) / len(tail))
    assert spread(filtered_speeds) < spread(raw_speeds) / 2


def test_velocity_is_bounded_relative_to_target_size():
    model = MotionModel(BBox(0, 0, 50, 100), max_speed_sizes_per_s=10.0)
    model.update(BBox(5000, 0, 50, 100), dt=0.001)
    assert math.hypot(model.vx, model.vy) <= 10.0 * 100 + 1e-6


def test_prediction_coast_is_capped():
    model = MotionModel(BBox(0, 0, 50, 100), max_coast_s=0.5)
    for i in range(1, 20):
        model.update(BBox(10.0 * i, 0, 50, 100), dt=0.1)
    assert model.predict(0.5).x == pytest.approx(model.predict(30.0).x)


def test_smooth_size_averages_out_box_size_jitter():
    model = MotionModel(BBox(0, 0, 50, 100))
    model.update(BBox(0, 0, 70, 100), dt=0.1)
    assert 50 < model.smooth_bbox.w < 70


def test_best_match_prefers_the_nearer_of_two_near_equal_overlaps():
    predicted = BBox(100, 100, 50, 100)
    far_ish = det(112, 100)     # slightly lower IoU, further from prediction
    near = det(106, 100)
    winner, _ = best_match(predicted, [far_ish, near], class_id=0, min_iou=0.3)
    assert winner is near


def test_best_match_ignores_other_classes_and_low_iou():
    predicted = BBox(100, 100, 50, 100)
    assert best_match(predicted, [det(100, 100, class_id=5)], class_id=0, min_iou=0.3) == (None, 0.0)
    winner, iou = best_match(predicted, [det(400, 400)], class_id=0, min_iou=0.3)
    assert winner is None


@pytest.mark.parametrize("tracker_cls", [IouKalmanTracker, ByteTrackTracker])
def test_tracker_reports_raw_box_and_a_smoothed_box(tracker_cls):
    tracker = tracker_cls()
    tracker.init_target(0.0, det(100, 100), target_id=1)
    result = tracker.update(0.1, [det(110, 100)])
    assert result.bbox.x == 110                 # raw detection preserved
    assert 100 < result.smooth_bbox.x < 110     # filtered box lags the jump
    assert result.guidance_bbox == result.smooth_bbox


@pytest.mark.parametrize("tracker_cls", [IouKalmanTracker, ByteTrackTracker])
def test_tracker_keeps_matching_a_steadily_moving_target(tracker_cls):
    tracker = tracker_cls()
    tracker.init_target(0.0, det(100, 100), target_id=1)
    for i in range(1, 60):
        result = tracker.update(0.033 * i, [det(100 + 4.0 * i, 100)])
        assert result is not None


@pytest.mark.parametrize("tracker_cls", [IouKalmanTracker, ByteTrackTracker])
def test_tracker_reacquires_after_a_short_gap_because_prediction_does_not_run_away(tracker_cls):
    """A long gap used to project the (stale) velocity for the whole gap, so
    the predicted box ended up far from where the target reappeared."""
    tracker = tracker_cls()
    tracker.init_target(0.0, det(100, 100), target_id=1)
    for i in range(1, 15):
        tracker.update(0.033 * i, [det(100 + 4.0 * i, 100)])
    last_x = 100 + 4.0 * 14
    # 1.5 seconds with no detections at all, then it reappears close to where it vanished.
    assert tracker.update(0.033 * 14 + 1.5, [det(last_x + 10, 100)]) is not None


@pytest.mark.parametrize("tracker_cls", [IouKalmanTracker, ByteTrackTracker])
def test_two_crossing_people_do_not_swap_when_one_is_clearly_nearer(tracker_cls):
    tracker = tracker_cls()
    tracker.init_target(0.0, det(200, 100), target_id=1)
    target_now = det(204, 100)
    bystander = det(240, 100)
    result = tracker.update(0.1, [bystander, target_now])
    assert result.bbox.x == 204
