from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pytest

from companion.comms.protocol import Envelope
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
from companion.vision.camera import CameraBase, Frame
from companion.vision.detector import PassthroughDetector


def _sent_envelopes_of_type(transport: FakeTransport, msg_type: str) -> list[Envelope]:
    return [e for e in (Envelope.from_json(raw) for raw in transport.sent) if e.type == msg_type]


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


def test_force_disarm_command_sends_the_documented_force_value(tmp_path):
    """A real field-reported bug: the app's DISARM button did nothing on a
    real bench test - ArduCopter was silently refusing the normal
    (unforced) disarm because its land-detector believed the aircraft was
    flying (see MavlinkBridge.arm()'s docstring). The Android "Force
    disarm" control sends {"armed": false, "force": true}; this proves
    _on_arm_command actually threads `force` through to the FC command."""
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._on_arm_command({"armed": False, "force": True})

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 21196, 0, 0, 0, 0, 0
        )
        recorder.close()


def test_arm_command_ignores_a_stray_force_flag(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._on_arm_command({"armed": True, "force": True})

        conn.mav.command_long_send.assert_called_once_with(
            1, 1, mock_mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0
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


@pytest.mark.asyncio
async def test_process_frame_resends_recording_state_with_a_growing_duration(tmp_path):
    """_handle_record_command only sends recording_state once, at the
    instant recording starts, with duration_s pinned at whatever it was
    then - a real bug reported from the field: the Android RecordButton's
    timer was frozen at 0:00 for the whole recording even though it was
    genuinely running on the Pi. process_frame() must keep resending
    recording_state every frame for as long as recording is active, with
    duration_s actually increasing, so the operator can tell it's alive."""
    video_recorder = VideoRecorder(tmp_path / "recordings", fps=10)
    with _build_orchestrator(
        tmp_path, video_recorder=video_recorder, camera=_FakeCamera()
    ) as (orchestrator, recorder, conn, mock_mavutil):
        orchestrator._frame_size = (64, 48)
        await orchestrator._handle_record_command(True)
        transport = orchestrator.link.transport
        transport.sent.clear()  # drop the one-shot message from the toggle above

        await orchestrator.process_frame(Frame(ts=0.0, width=64, height=48, raw_detection_output=[]))
        first_batch = _sent_envelopes_of_type(transport, "recording_state")
        assert len(first_batch) == 1
        assert first_batch[0].payload["recording"] is True
        first_duration = first_batch[0].payload["duration_s"]

        await orchestrator.process_frame(Frame(ts=0.1, width=64, height=48, raw_detection_output=[]))
        second_batch = _sent_envelopes_of_type(transport, "recording_state")
        assert len(second_batch) == 2
        assert second_batch[1].payload["duration_s"] >= first_duration

        video_recorder.stop()
        recorder.close()


@pytest.mark.asyncio
async def test_process_frame_sends_no_recording_state_when_not_recording(tmp_path):
    with _build_orchestrator(tmp_path, video_recorder=None, camera=_FakeCamera()) as (
        orchestrator, recorder, conn, mock_mavutil,
    ):
        transport = orchestrator.link.transport

        await orchestrator.process_frame(Frame(ts=0.0, width=64, height=48, raw_detection_output=[]))

        assert _sent_envelopes_of_type(transport, "recording_state") == []
        recorder.close()
