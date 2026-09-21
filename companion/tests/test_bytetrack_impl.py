from companion.tracking.bytetrack_impl import ByteTrackTracker
from companion.vision.detector import BBox, Detection


def make_det(ts, x, y, w=50, h=100, class_id=0, class_name="person", score=0.9):
    return Detection(
        bbox=BBox(x, y, w, h), score=score, class_id=class_id, class_name=class_name, frame_ts=ts
    )


def test_init_and_update_follows_moving_detection():
    tracker = ByteTrackTracker()
    tracker.init_target(0.0, make_det(0.0, 100, 100), target_id=1)

    result = tracker.update(0.1, [make_det(0.1, 105, 100)])
    assert result is not None
    assert result.target_id == 1
    assert result.bbox.x == 105


def test_update_returns_none_when_no_matching_class():
    tracker = ByteTrackTracker()
    tracker.init_target(0.0, make_det(0.0, 100, 100, class_id=0), target_id=1)

    result = tracker.update(0.1, [make_det(0.1, 100, 100, class_id=5)])
    assert result is None


def test_update_returns_none_below_min_iou():
    tracker = ByteTrackTracker(min_iou=0.5)
    tracker.init_target(0.0, make_det(0.0, 0, 0, w=50, h=50), target_id=1)

    far_detection = make_det(0.1, 1000, 1000, w=50, h=50)
    assert tracker.update(0.1, [far_detection]) is None


def test_reset_clears_target():
    tracker = ByteTrackTracker()
    tracker.init_target(0.0, make_det(0.0, 0, 0), target_id=1)
    tracker.reset()
    assert tracker.update(0.1, [make_det(0.1, 0, 0)]) is None


def test_stage_one_prefers_a_high_confidence_match_over_a_low_confidence_one():
    """When a high-score detection matches well enough, stage 2 (the "Byte"
    low-confidence retry) must never even be considered - a strong, fresh
    detection should always win over a stale/uncertain one."""
    tracker = ByteTrackTracker(high_score_thresh=0.6, low_score_thresh=0.1)
    tracker.init_target(0.0, make_det(0.0, 100, 100), target_id=1)

    high_conf_match = make_det(0.1, 105, 100, score=0.9)
    low_conf_overlapping = make_det(0.1, 106, 100, score=0.2)
    result = tracker.update(0.1, [low_conf_overlapping, high_conf_match])
    assert result.confidence == 0.9
    assert result.bbox.x == 105


def test_stage_two_recovers_using_a_low_confidence_detection_a_score_cutoff_would_hide():
    """The actual point of ByteTrack over plain IoU tracking: a real object
    that only produced a low-confidence box this frame (occlusion, motion
    blur, bad angle) is still recoverable, instead of being treated the
    same as a genuinely missing detection."""
    tracker = ByteTrackTracker(high_score_thresh=0.6, low_score_thresh=0.1)
    tracker.init_target(0.0, make_det(0.0, 100, 100), target_id=1)

    only_a_low_confidence_box = make_det(0.1, 105, 100, score=0.15)
    result = tracker.update(0.1, [only_a_low_confidence_box])
    assert result is not None
    assert result.target_id == 1
    assert result.bbox.x == 105
    assert result.confidence == 0.15


def test_detections_below_low_score_thresh_are_never_matched_even_as_a_last_resort():
    tracker = ByteTrackTracker(high_score_thresh=0.6, low_score_thresh=0.1)
    tracker.init_target(0.0, make_det(0.0, 100, 100), target_id=1)

    below_the_byte_floor = make_det(0.1, 105, 100, score=0.05)
    assert tracker.update(0.1, [below_the_byte_floor]) is None


def test_a_low_confidence_detection_must_still_clear_the_iou_threshold():
    tracker = ByteTrackTracker(high_score_thresh=0.6, low_score_thresh=0.1, min_iou=0.5)
    tracker.init_target(0.0, make_det(0.0, 0, 0, w=50, h=50), target_id=1)

    far_but_low_confidence = make_det(0.1, 1000, 1000, w=50, h=50, score=0.2)
    assert tracker.update(0.1, [far_but_low_confidence]) is None
