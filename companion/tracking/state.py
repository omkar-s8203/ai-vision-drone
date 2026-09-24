from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from companion.tracking.base import TrackedTarget, Tracker
from companion.vision.detector import Detection


class TrackingState(Enum):
    IDLE = auto()
    TRACKING = auto()
    REACQUIRE = auto()
    TARGET_LOST = auto()


class TrackingStateMachine:
    """Owns the TRACKING -> REACQUIRE -> TARGET_LOST lifecycle for a single
    selected target. Never exposes stale coordinates once TARGET_LOST -
    callers must check `state` before consuming `target`.
    """

    def __init__(self, tracker: Tracker, reacquire_timeout_s: float = 2.0) -> None:
        self.tracker = tracker
        self.reacquire_timeout_s = reacquire_timeout_s
        self.state = TrackingState.IDLE
        self.target: Optional[TrackedTarget] = None
        self._lost_since_ts: Optional[float] = None
        self._next_target_id = 1

    def start(self, frame_ts: float, detection: Detection) -> TrackedTarget:
        target_id = self._next_target_id
        self._next_target_id += 1
        self.target = self.tracker.init_target(frame_ts, detection, target_id)
        self.state = TrackingState.TRACKING
        self._lost_since_ts = None
        return self.target

    def update(self, frame_ts: float, detections: list[Detection]) -> TrackingState:
        if self.state == TrackingState.IDLE:
            return self.state

        result = self.tracker.update(frame_ts, detections)

        if result is not None:
            self.target = result
            self.state = TrackingState.TRACKING
            self._lost_since_ts = None
            return self.state

        if self.state == TrackingState.TRACKING:
            self.state = TrackingState.REACQUIRE
            self._lost_since_ts = frame_ts
            return self.state

        if self.state == TrackingState.REACQUIRE:
            assert self._lost_since_ts is not None
            if frame_ts - self._lost_since_ts >= self.reacquire_timeout_s:
                self.state = TrackingState.TARGET_LOST
                self.target = None
            return self.state

        return self.state

    def drop_identity(self, frame_ts: float) -> None:
        """The tracker is still matching a box, but it's judged to be the
        wrong subject: forget the tracker's own lock (otherwise it would
        immediately re-latch onto the same wrong box next frame) and enter
        REACQUIRE, whose existing timeout then hands over to the normal
        TARGET_LOST handling / appearance-based reacquisition."""
        if self.state != TrackingState.TRACKING:
            return
        self.tracker.reset()
        self.state = TrackingState.REACQUIRE
        self._lost_since_ts = frame_ts

    def stop(self) -> None:
        self.tracker.reset()
        self.state = TrackingState.IDLE
        self.target = None
        self._lost_since_ts = None
