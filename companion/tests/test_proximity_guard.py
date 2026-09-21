from companion.config.loader import load_yaml
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator, DistanceSource
from companion.safety.proximity_guard import check_proximity
from companion.vision.detector import BBox, Detection

CALIB = load_yaml("camera_calibration.yaml")
MIN_SAFE_DISTANCE_M = 2.0


class _FixedDistanceSource(DistanceSource):
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


def make_detection(class_name: str, bbox_w: float) -> Detection:
    return Detection(
        bbox=BBox(x=0, y=0, w=bbox_w, h=bbox_w * 2),
        score=0.9,
        class_id=0,
        class_name=class_name,
        frame_ts=0.0,
    )


def test_no_detections_returns_none():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB))
    assert check_proximity([], estimator, MIN_SAFE_DISTANCE_M) is None


def test_far_object_does_not_trigger():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB))
    far_person = make_detection("person", bbox_w=100)  # (0.5*900)/100 = 4.5m
    assert check_proximity([far_person], estimator, MIN_SAFE_DISTANCE_M) is None


def test_close_object_triggers_alert():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB))
    close_person = make_detection("person", bbox_w=300)  # (0.5*900)/300 = 1.5m
    alert = check_proximity([close_person], estimator, MIN_SAFE_DISTANCE_M)
    assert alert is not None
    assert alert.class_name == "person"
    assert alert.distance_m < MIN_SAFE_DISTANCE_M


def test_checks_every_detection_not_just_the_first():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB))
    far_car = make_detection("car", bbox_w=50)  # (1.8*900)/50 = 32.4m
    close_person = make_detection("person", bbox_w=300)  # 1.5m
    alert = check_proximity([far_car, close_person], estimator, MIN_SAFE_DISTANCE_M)
    assert alert is not None
    assert alert.class_name == "person"


def test_returns_the_closest_when_multiple_are_too_close():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB))
    somewhat_close = make_detection("person", bbox_w=250)  # (0.5*900)/250 = 1.8m
    very_close = make_detection("person", bbox_w=450)  # (0.5*900)/450 = 1.0m

    alert = check_proximity([somewhat_close, very_close], estimator, MIN_SAFE_DISTANCE_M)
    assert alert is not None
    assert alert.distance_m == 1.0


def test_unknown_class_with_no_known_width_is_skipped_safely():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB))
    mystery_object = make_detection("skateboard", bbox_w=500)  # not in KNOWN_OBJECT_WIDTHS_M
    assert check_proximity([mystery_object], estimator, MIN_SAFE_DISTANCE_M) is None


def test_rangefinder_is_only_trusted_for_the_tracked_target():
    """A forward-facing rangefinder gives one boresight reading per frame -
    applying it to every detection would report the tracked target's own
    distance for unrelated objects too (docs/safety-case.md). Here the
    rangefinder claims 1.0m (would trigger an alert); the untracked car's
    real vision-estimated distance is a safe 32.4m, so it must NOT alert
    just because a rangefinder happens to be present this frame."""
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB), rangefinder=_FixedDistanceSource(1.0))
    untracked_far_car = make_detection("car", bbox_w=50)  # (1.8*900)/50 = 32.4m by vision
    assert check_proximity([untracked_far_car], estimator, MIN_SAFE_DISTANCE_M) is None


def test_rangefinder_reading_is_applied_to_the_matching_tracked_target():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB), rangefinder=_FixedDistanceSource(1.0))
    tracked_person = make_detection("person", bbox_w=100)  # vision would say 4.5m, safely far
    alert = check_proximity([tracked_person], estimator, MIN_SAFE_DISTANCE_M, tracked_target=tracked_person)
    assert alert is not None
    assert alert.distance_m == 1.0  # the rangefinder reading won, not the vision estimate


def test_only_the_matching_detection_trusts_the_rangefinder_not_the_rest():
    estimator = DistanceEstimator(CameraIntrinsics.from_dict(CALIB), rangefinder=_FixedDistanceSource(1.0))
    tracked_person = make_detection("person", bbox_w=100)  # tracked: rangefinder says 1.0m
    untracked_far_car = make_detection("car", bbox_w=50)  # untracked: vision says 32.4m, safe
    alert = check_proximity(
        [tracked_person, untracked_far_car], estimator, MIN_SAFE_DISTANCE_M, tracked_target=tracked_person
    )
    assert alert is not None
    assert alert.class_name == "person"
    assert alert.distance_m == 1.0
