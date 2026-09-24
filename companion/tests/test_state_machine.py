from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState, TrackingStateMachine
from companion.vision.detector import BBox, Detection


def make_det(ts, x=100, y=100, w=50, h=100, class_id=0):
    return Detection(bbox=BBox(x, y, w, h), score=0.9, class_id=class_id, class_name="person", frame_ts=ts)


def test_start_enters_tracking_state():
    sm = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=1.0)
    sm.start(0.0, make_det(0.0))
    assert sm.state == TrackingState.TRACKING
    assert sm.target is not None


def test_missed_frame_enters_reacquire_then_target_lost_after_timeout():
    sm = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=1.0)
    sm.start(0.0, make_det(0.0))

    # no detections this frame -> should enter REACQUIRE, not TARGET_LOST yet
    state = sm.update(0.2, [])
    assert state == TrackingState.REACQUIRE
    assert sm.target is not None  # not stale-consumed yet, caller still knows we're recovering

    # still within timeout (elapsed since loss at 0.2s is < 1.0s)
    state = sm.update(0.9, [])
    assert state == TrackingState.REACQUIRE

    # timeout exceeded (elapsed since loss at 0.2s is now 1.1s) -> TARGET_LOST
    state = sm.update(1.3, [])
    assert state == TrackingState.TARGET_LOST
    assert sm.target is None


def test_reacquire_recovers_to_tracking_on_match():
    sm = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=1.0)
    sm.start(0.0, make_det(0.0))
    sm.update(0.2, [])
    assert sm.state == TrackingState.REACQUIRE

    state = sm.update(0.3, [make_det(0.3, x=102, y=100)])
    assert state == TrackingState.TRACKING
    assert sm.target is not None


def test_stop_resets_to_idle():
    sm = TrackingStateMachine(IouKalmanTracker())
    sm.start(0.0, make_det(0.0))
    sm.stop()
    assert sm.state == TrackingState.IDLE
    assert sm.target is None


# --- frames with no AI result (coast) -----------------------------------------

def test_coast_keeps_tracking_and_does_not_touch_the_tracker():
    tracker = IouKalmanTracker()
    sm = TrackingStateMachine(tracker, reacquire_timeout_s=1.0)
    target = sm.start(0.0, make_det(0.0))
    assert sm.coast(0.1) == TrackingState.TRACKING
    assert sm.coast(0.2) == TrackingState.TRACKING
    assert sm.target is target


def test_coasting_does_not_break_the_next_real_match():
    """The tracker's motion prediction spans the whole gap since the target
    was last seen, so skipped frames do not cost the association."""
    sm = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=1.0)
    sm.start(0.0, make_det(0.0))
    sm.coast(0.033)
    sm.coast(0.066)
    assert sm.update(0.1, [make_det(0.1, x=103)]) == TrackingState.TRACKING
    assert sm.target.last_seen_ts == 0.1


def test_coast_still_runs_out_an_active_reacquire_timeout():
    sm = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=1.0)
    sm.start(0.0, make_det(0.0))
    sm.update(0.2, [])
    assert sm.coast(0.9) == TrackingState.REACQUIRE
    assert sm.coast(1.3) == TrackingState.TARGET_LOST
    assert sm.target is None


def test_coast_is_a_no_op_when_idle():
    sm = TrackingStateMachine(IouKalmanTracker())
    assert sm.coast(1.0) == TrackingState.IDLE
