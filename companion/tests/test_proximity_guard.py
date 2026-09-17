from companion.config.loader import load_yaml
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.safety.proximity_guard import check_proximity
from companion.vision.detector import BBox, Detection

CALIB = load_yaml("camera_calibration.yaml")
MIN_SAFE_DISTANCE_M = 2.0


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
