from companion.tracking.target_selector import select_target
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
