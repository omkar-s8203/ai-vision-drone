from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.detector import BBox, Detection


def make_det(ts, x, y, w=50, h=100, class_id=0, class_name="person"):
    return Detection(bbox=BBox(x, y, w, h), score=0.9, class_id=class_id, class_name=class_name, frame_ts=ts)


def test_init_and_update_follows_moving_detection():
    tracker = IouKalmanTracker()
    tracker.init_target(0.0, make_det(0.0, 100, 100), target_id=1)

    result = tracker.update(0.1, [make_det(0.1, 105, 100)])
    assert result is not None
    assert result.target_id == 1
    assert result.bbox.x == 105


def test_update_returns_none_when_no_matching_class():
    tracker = IouKalmanTracker()
    tracker.init_target(0.0, make_det(0.0, 100, 100, class_id=0), target_id=1)

    result = tracker.update(0.1, [make_det(0.1, 100, 100, class_id=5)])
    assert result is None


def test_update_returns_none_below_min_iou():
    tracker = IouKalmanTracker(min_iou=0.5)
    tracker.init_target(0.0, make_det(0.0, 0, 0, w=50, h=50), target_id=1)

    far_detection = make_det(0.1, 1000, 1000, w=50, h=50)
    assert tracker.update(0.1, [far_detection]) is None


def test_reset_clears_target():
    tracker = IouKalmanTracker()
    tracker.init_target(0.0, make_det(0.0, 0, 0), target_id=1)
    tracker.reset()
    assert tracker.update(0.1, [make_det(0.1, 0, 0)]) is None
