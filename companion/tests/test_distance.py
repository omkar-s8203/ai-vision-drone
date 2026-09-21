from companion.guidance.distance import (
    CameraIntrinsics,
    DistanceEstimator,
    DistanceSource,
    estimate_distance_pinhole_m,
)
from companion.vision.detector import BBox, Detection

INTRINSICS = CameraIntrinsics(image_width=1280, image_height=720, fx=900.0, fy=900.0, cx=640.0, cy=360.0)


def make_det(w, class_name="person"):
    return Detection(bbox=BBox(0, 0, w, 100), score=0.9, class_id=0, class_name=class_name, frame_ts=0.0)


def test_pinhole_distance_known_class():
    # distance = real_width(0.5m) * fx(900) / pixel_width(45) = 10.0m
    det = make_det(w=45)
    assert estimate_distance_pinhole_m(det, INTRINSICS) == 10.0


def test_pinhole_distance_unknown_class_returns_none():
    det = make_det(w=45, class_name="unicorn")
    assert estimate_distance_pinhole_m(det, INTRINSICS) is None


def test_pinhole_distance_zero_width_returns_none():
    det = make_det(w=0)
    assert estimate_distance_pinhole_m(det, INTRINSICS) is None


class _FixedDistanceSource(DistanceSource):
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


def test_estimator_prefers_rangefinder_when_trusted_and_available():
    estimator = DistanceEstimator(INTRINSICS, rangefinder=_FixedDistanceSource(3.5))
    distance, source = estimator.estimate(make_det(w=45), trust_rangefinder=True)
    assert distance == 3.5
    assert source == "rangefinder"


def test_estimator_falls_back_to_vision_without_rangefinder():
    estimator = DistanceEstimator(INTRINSICS)
    distance, source = estimator.estimate(make_det(w=45), trust_rangefinder=True)
    assert distance == 10.0
    assert source == "vision"


def test_estimator_ignores_rangefinder_by_default_even_when_available():
    """A forward-facing rangefinder gives one boresight reading per frame,
    not a per-object one - applying it to a detection the caller hasn't
    vouched for as the tracked target would silently misreport that
    object's distance as the tracked target's own (docs/safety-case.md).
    trust_rangefinder must default to False."""
    estimator = DistanceEstimator(INTRINSICS, rangefinder=_FixedDistanceSource(3.5))
    distance, source = estimator.estimate(make_det(w=45))
    assert distance == 10.0
    assert source == "vision"
