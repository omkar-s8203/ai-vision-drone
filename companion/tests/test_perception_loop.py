"""Tests for CompanionOrchestrator._perception_loop's exception isolation -
a real robustness gap found in a code-review audit: process_frame() used to
run with no exception handling at all, so a bug anywhere in it would
propagate straight out of the camera loop, killing capture/video/MAVLink/
telemetry all at once over what might only be one bad frame.
"""

from unittest.mock import AsyncMock, patch

import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.camera import CameraBase, Frame
from companion.vision.detector import PassthroughDetector


class _FakeCamera(CameraBase):
    """Yields a fixed number of frames then stops - just enough to prove
    the loop keeps going past a frame that made process_frame() raise."""

    def __init__(self, count: int) -> None:
        self.count = count

    async def frames(self):
        for i in range(self.count):
            yield Frame(ts=float(i), width=1280, height=720, raw_detection_output=[])


def _build_orchestrator(tmp_path, camera):
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path)
    return CompanionOrchestrator(
        camera=camera,
        detector=PassthroughDetector(),
        tracker=IouKalmanTracker(),
        distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
        follow_controller=FollowController(follow_cfg),
        orbit_controller=OrbitController(orbit_cfg),
        approach_controller=ApproachTestController(approach_cfg),
        mavlink=MavlinkBridge("udpin:127.0.0.1:14690"),
        rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
        supervisor=SafetySupervisor(watchdog),
        watchdog=watchdog,
        link=link,
        recorder=recorder,
    )


@pytest.mark.asyncio
async def test_a_frame_that_raises_does_not_stop_the_camera_loop(tmp_path):
    orchestrator = _build_orchestrator(tmp_path, _FakeCamera(count=3))

    call_count = 0

    async def fake_process_frame(frame):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ValueError("boom - simulates a bug in some guidance controller")
        return {}

    with patch.object(orchestrator, "process_frame", side_effect=fake_process_frame):
        await orchestrator._perception_loop()  # must not raise

    assert call_count == 3  # frame 2 raised, but frames 1 and 3 still ran
    orchestrator.recorder.close()


@pytest.mark.asyncio
async def test_every_frame_raising_still_leaves_the_loop_running_to_completion(tmp_path):
    orchestrator = _build_orchestrator(tmp_path, _FakeCamera(count=5))
    mock_process_frame = AsyncMock(side_effect=RuntimeError("always fails"))

    with patch.object(orchestrator, "process_frame", mock_process_frame):
        await orchestrator._perception_loop()  # must not raise even if every frame fails

    assert mock_process_frame.await_count == 5
    orchestrator.recorder.close()
