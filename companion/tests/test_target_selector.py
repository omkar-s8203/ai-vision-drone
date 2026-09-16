from companion.tracking.target_selector import select_target, select_target_at_point
from companion.vision.detector import BBox, Detection


def make_det(x, y, w, h, class_name="person"):
    return Detection(bbox=BBox(x, y, w, h), score=0.9, class_id=0, class_name=class_name, frame_ts=0.0)


def test_selects_best_overlapping_detection():
    detections = [make_det(0, 0, 10, 10), make_det(100, 100, 10, 10)]
    selection = BBox(1, 1, 9, 9)
    selected = select_target(detections, selection)
    assert selected is detections[0]


def test_returns_none_when_no_overlap():
    detections = [make_det(0, 0, 10, 10)]
    selection = BBox(500, 500, 10, 10)
    assert select_target(detections, selection) is None


def test_returns_none_for_empty_detections():
    assert select_target([], BBox(0, 0, 10, 10)) is None


def test_point_selects_containing_detection():
    detections = [make_det(0, 0, 10, 10, "person"), make_det(100, 100, 10, 10, "car")]
    assert select_target_at_point(detections, x=5, y=5) is detections[0]
    assert select_target_at_point(detections, x=105, y=105) is detections[1]


def test_point_outside_all_boxes_returns_none():
    detections = [make_det(0, 0, 10, 10)]
    assert select_target_at_point(detections, x=500, y=500) is None


def test_point_in_overlapping_boxes_picks_smallest():
    """Tapping a person standing in front of a car should select the
    person (smaller box), not the car behind them."""
    car = make_det(0, 0, 100, 100, "car")
    person = make_det(40, 40, 20, 20, "person")
    detections = [car, person]
    assert select_target_at_point(detections, x=50, y=50) is person


def test_point_on_box_edge_is_included():
    detections = [make_det(0, 0, 10, 10)]
    assert select_target_at_point(detections, x=0, y=0) is detections[0]
    assert select_target_at_point(detections, x=10, y=10) is detections[0]
