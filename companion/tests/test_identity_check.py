import numpy as np
import pytest

from companion.tracking.appearance import AppearanceMemory
from companion.tracking.base import TrackedTarget
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState, TrackingStateMachine
from companion.vision.detector import BBox, Detection

RED = (0, 0, 255)
BLUE = (255, 0, 0)


def frame_with(box, color, size=(400, 400)):
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:, :] = (0, 255, 0)
    img[int(box.y):int(box.y + box.h), int(box.x):int(box.x + box.w)] = color
    return img


def target_at(box):
    return TrackedTarget(
        target_id=1, bbox=box, confidence=0.9, class_id=0, class_name="person", last_seen_ts=0.0
    )


BOX = BBox(100, 100, 60, 120)


def test_same_appearance_scores_high():
    memory = AppearanceMemory()
    memory.learn(frame_with(BOX, RED), target_at(BOX))
    assert memory.check_identity(frame_with(BOX, RED), target_at(BOX)) > 0.9


def test_a_different_looking_subject_scores_low():
    memory = AppearanceMemory()
    memory.learn(frame_with(BOX, RED), target_at(BOX))
    score = memory.check_identity(frame_with(BOX, BLUE), target_at(BOX))
    assert score < memory.track_min_similarity


def test_returns_none_when_nothing_can_be_judged():
    memory = AppearanceMemory()
    assert memory.check_identity(frame_with(BOX, RED), target_at(BOX)) is None  # no signature yet
    memory.learn(frame_with(BOX, RED), target_at(BOX))
    assert memory.check_identity(None, target_at(BOX)) is None  # no real frame (sim)
    off_frame = BBox(900, 900, 50, 50)
    assert memory.check_identity(frame_with(BOX, RED), target_at(off_frame)) is None


def test_a_strong_match_nudges_the_signature_toward_the_current_look():
    memory = AppearanceMemory(adapt_rate=0.5, adapt_similarity=-1.0)  # threshold low enough to always adapt
    memory.learn(frame_with(BOX, RED), target_at(BOX))
    before = memory._signature.histogram.copy()
    memory.check_identity(frame_with(BOX, BLUE), target_at(BOX))
    after = memory._signature.histogram
    assert not np.array_equal(before, after)
    assert after.max() <= before.max()  # a blend, not a replacement


def test_a_weak_match_never_contaminates_the_signature():
    memory = AppearanceMemory()
    memory.learn(frame_with(BOX, RED), target_at(BOX))
    before = memory._signature.histogram.copy()
    memory.check_identity(frame_with(BOX, BLUE), target_at(BOX))
    assert np.array_equal(before, memory._signature.histogram)


def test_check_uses_the_smoothed_box_when_present():
    memory = AppearanceMemory()
    memory.learn(frame_with(BOX, RED), target_at(BOX))
    jittery = target_at(BBox(300, 300, 60, 120))  # raw detection landed on background
    jittery.smooth_bbox = BOX                       # filtered box is still on the subject
    assert memory.check_identity(frame_with(BOX, RED), jittery) > 0.9


def _machine():
    machine = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=1.0)
    det = Detection(bbox=BOX, score=0.9, class_id=0, class_name="person", frame_ts=0.0)
    machine.start(0.0, det)
    return machine, det


def test_drop_identity_enters_reacquire_and_the_tracker_does_not_relatch():
    machine, det = _machine()
    machine.drop_identity(0.1)
    assert machine.state == TrackingState.REACQUIRE
    # The same (wrong) box is still there - the tracker must not silently re-lock onto it.
    assert machine.update(0.2, [det]) == TrackingState.REACQUIRE
    assert machine.update(0.3, [det]) == TrackingState.REACQUIRE


def test_a_dropped_identity_times_out_into_target_lost():
    machine, det = _machine()
    machine.drop_identity(0.1)
    assert machine.update(1.2, [det]) == TrackingState.TARGET_LOST
    assert machine.target is None


def test_drop_identity_is_a_no_op_unless_tracking():
    machine = TrackingStateMachine(IouKalmanTracker())
    machine.drop_identity(0.0)
    assert machine.state == TrackingState.IDLE
