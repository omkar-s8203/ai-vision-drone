from companion.vision.detector import BBox


def test_identical_boxes_have_iou_one():
    a = BBox(0, 0, 10, 10)
    b = BBox(0, 0, 10, 10)
    assert a.iou(b) == 1.0


def test_disjoint_boxes_have_iou_zero():
    a = BBox(0, 0, 10, 10)
    b = BBox(100, 100, 10, 10)
    assert a.iou(b) == 0.0


def test_partial_overlap():
    a = BBox(0, 0, 10, 10)
    b = BBox(5, 0, 10, 10)
    # intersection = 5x10=50, union = 100+100-50=150
    assert abs(a.iou(b) - 50 / 150) < 1e-9
