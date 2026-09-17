from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pytest

from companion.comms.video_recorder import VideoRecorder
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
from companion.vision.camera import CameraBase
from companion.vision.detector import PassthroughDetector


class _FakeCamera(CameraBase):
    """Stands in for a real camera in tests that need get_latest_frame() to
    return actual pixel data (video recording), without needing picamera2."""

    def __init__(self) -> None:
        self.width = 64
        self.height = 48
        self._frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def get_latest_frame(self):
        return self._frame


@contextmanager
def _build_orchestrator(tmp_path, video_recorder=None, camera=None):
    """A context manager (not a plain function) because the mavutil patch
    must stay active for the whole test body - MavlinkBridge.arm()/set_mode()
    read `mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM` etc. at call time,
    not just at connect() time, so the patch has to still be in effect when
    the test invokes the handler under test, not just while building the
    orchestrator."""
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path / "session")
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14690")
        mavlink.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
        orchestrator = CompanionOrchestrator(
            camera=camera,
            detector=PassthroughDetector(),
            tracker=IouKalmanTracker(),
            distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg)),
            follow_controller=FollowController(follow_cfg),
            orbit_controller=OrbitController(orbit_cfg),
            approach_controller=ApproachTestController(approach_cfg),
            mavlink=mavlink,
            rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
            supervisor=SafetySupervisor(watchdog),
            watchdog=watchdog,
            link=link,
            recorder=recorder,
            video_recorder=video_recorder,
        )
        yield orchestrator, recorder, conn, mock_mavutil


def test_arm_command_sends_component_arm_disarm(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._on_arm_command({"armed": True})

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0
        )
        recorder.close()


def test_disarm_command_sends_param1_zero(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._on_arm_command({"armed": False})

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0
        )
        recorder.close()


def test_set_flight_mode_command_sends_correct_mode_number(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._on_set_flight_mode({"mode": "RTL"})

        conn.mav.set_mode_send.assert_called_once_with(1, 1, 6)  # RTL = 6
        recorder.close()


def test_set_flight_mode_command_unknown_mode_is_a_safe_no_op(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._on_set_flight_mode({"mode": "NOT_A_REAL_MODE"})

        conn.mav.set_mode_send.assert_not_called()
        recorder.close()


@pytest.mark.asyncio
async def test_record_command_starts_and_reports_recording_state(tmp_path):
    video_recorder = VideoRecorder(tmp_path / "recordings", fps=10)
    with _build_orchestrator(
        tmp_path, video_recorder=video_recorder, camera=_FakeCamera()
    ) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._frame_size = (64, 48)

        await orchestrator._handle_record_command(True)

        assert video_recorder.is_recording is True
        video_recorder.stop()
        recorder.close()


@pytest.mark.asyncio
async def test_record_command_stop_releases_the_writer(tmp_path):
    video_recorder = VideoRecorder(tmp_path / "recordings", fps=10)
    with _build_orchestrator(
        tmp_path, video_recorder=video_recorder, camera=_FakeCamera()
    ) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._frame_size = (64, 48)
        await orchestrator._handle_record_command(True)

        await orchestrator._handle_record_command(False)

        assert video_recorder.is_recording is False
        recorder.close()


@pytest.mark.asyncio
async def test_record_command_without_a_video_recorder_is_a_safe_no_op(tmp_path):
    with _build_orchestrator(tmp_path, video_recorder=None) as (orchestrator, recorder, conn, mock_mavutil):
        await orchestrator._handle_record_command(True)  # must not raise

        recorder.close()
