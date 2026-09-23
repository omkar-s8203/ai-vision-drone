from contextlib import contextmanager
from unittest.mock import patch

import pytest

from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.auto_takeoff import AutoTakeoffPhase
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator, SupervisorState
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.vision.camera import Frame
from companion.vision.detector import BBox, Detection, PassthroughDetector


@contextmanager
def _build_connected_orchestrator(tmp_path):
    """Mirrors test_mode_command.py's helper of the same name - MavlinkBridge
    must actually be connect()-ed (with mavutil mocked) since this exercises
    real MavlinkBridge.takeoff()/send_velocity_setpoint() calls, both of
    which assert a live connection."""
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    link = GroundStationLink(FakeTransport(connected=True))
    recorder = SessionRecorder(tmp_path)
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14760")
        mavlink.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
        orchestrator = CompanionOrchestrator(
            camera=None,
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
        )
        yield orchestrator, recorder, conn


def _person():
    return Detection(bbox=BBox(600, 300, 80, 160), score=0.9, class_id=0, class_name="person", frame_ts=0.0)


@pytest.mark.asyncio
async def test_arm_and_follow_holds_guidance_until_altitude_then_starts_following(tmp_path):
    """The exact field request this feature exists for: 'Arm & Follow should
    gain height, then start following.' Proves the full real sequence -
    Follow must not compute/send a single velocity setpoint until armed, in
    GUIDED, and the takeoff climb has actually reached altitude; only then
    does real Follow guidance take over, in the same frame auto-takeoff
    reports 'ready'."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.watchdog.beat("mavlink")
        orchestrator.watchdog.beat("rc_channels")
        orchestrator.mavlink.telemetry.fc_mode = "STABILIZE"
        orchestrator.mavlink.telemetry.armed = False
        orchestrator.mavlink.telemetry.alt_m = 0.0
        person = _person()

        orchestrator._on_target_selected({"x": 640.0, "y": 380.0, "point": True})
        await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[person]))

        orchestrator._on_mode_command({"mode": "follow", "auto_takeoff": True})
        assert orchestrator.auto_takeoff.is_active
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.WAITING_TO_ARM

        # Simulates the FC's own HEARTBEAT confirming the auto-GUIDED-request
        # (set_mode_send) that _on_mode_command already fired above.
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"

        # Not armed yet - must hold, no takeoff sent, no velocity setpoint.
        await orchestrator.process_frame(Frame(ts=0.1, width=1280, height=720, raw_detection_output=[person]))
        conn.mav.command_long_send.assert_not_called()
        conn.mav.set_position_target_local_ned_send.assert_not_called()
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.WAITING_TO_ARM

        # Now armed (simulates the operator's separate arm command landing).
        orchestrator.mavlink.telemetry.armed = True

        await orchestrator.process_frame(Frame(ts=0.2, width=1280, height=720, raw_detection_output=[person]))
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.CLIMBING
        conn.mav.set_position_target_local_ned_send.assert_not_called()
        # Identified by its trailing altitude param (10.0) - the only other
        # command_long_send in this sequence (MAV_CMD_GET_HOME_POSITION, on
        # the arm edge-detect) sends all-zero params.
        takeoff_calls = [call for call in conn.mav.command_long_send.call_args_list if call.args[-1] == 10.0]
        assert len(takeoff_calls) == 1

        # Still climbing, below tolerance - held, no repeat takeoff command.
        orchestrator.mavlink.telemetry.alt_m = 5.0
        await orchestrator.process_frame(Frame(ts=0.3, width=1280, height=720, raw_detection_output=[person]))
        conn.mav.set_position_target_local_ned_send.assert_not_called()
        takeoff_calls = [call for call in conn.mav.command_long_send.call_args_list if call.args[-1] == 10.0]
        assert len(takeoff_calls) == 1
        assert orchestrator.auto_takeoff.is_active

        # Altitude reached (within the 1.0m tolerance of a 10.0m target) -
        # sequencing completes and real Follow guidance starts this frame.
        orchestrator.mavlink.telemetry.alt_m = 9.5
        await orchestrator.process_frame(Frame(ts=0.4, width=1280, height=720, raw_detection_output=[person]))
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.DONE
        assert not orchestrator.auto_takeoff.is_active
        conn.mav.set_position_target_local_ned_send.assert_called()

        recorder.close()


@pytest.mark.asyncio
async def test_auto_takeoff_timeout_aborts_to_idle_without_ever_following(tmp_path):
    """If the aircraft never reaches altitude within timeout_s, this must
    fail toward idle rather than silently holding Follow forever with
    nothing observable happening - mirrors the rejected-grid-search-start
    failure mode."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.watchdog.beat("mavlink")
        orchestrator.watchdog.beat("rc_channels")
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
        orchestrator.mavlink.telemetry.armed = True
        orchestrator.mavlink.telemetry.alt_m = 0.0
        person = _person()

        orchestrator._on_target_selected({"x": 640.0, "y": 380.0, "point": True})
        await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[person]))

        orchestrator._on_mode_command({"mode": "follow", "auto_takeoff": True})

        # Sends the takeoff command, enters CLIMBING.
        await orchestrator.process_frame(Frame(ts=0.1, width=1280, height=720, raw_detection_output=[person]))
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.CLIMBING

        # Altitude never rises above 0 - 31s later (> the 30s config
        # timeout), this must give up rather than hold forever.
        await orchestrator.process_frame(Frame(ts=31.1, width=1280, height=720, raw_detection_output=[person]))

        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.TIMED_OUT
        assert orchestrator.requested_mode == SupervisorState.IDLE
        conn.mav.set_position_target_local_ned_send.assert_not_called()

        recorder.close()


def test_switching_mode_away_mid_sequence_resets_auto_takeoff(tmp_path):
    """A takeoff sequence started for Follow must not silently carry over to
    whatever the operator switches to next."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"

        orchestrator._on_mode_command({"mode": "follow", "auto_takeoff": True})
        assert orchestrator.auto_takeoff.is_active

        orchestrator._on_mode_command({"mode": "orbit"})

        assert not orchestrator.auto_takeoff.is_active
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.IDLE
        recorder.close()


def test_abort_mid_sequence_resets_auto_takeoff(tmp_path):
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"

        orchestrator._on_mode_command({"mode": "follow", "auto_takeoff": True})
        assert orchestrator.auto_takeoff.is_active

        orchestrator._on_abort({})

        assert not orchestrator.auto_takeoff.is_active
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.IDLE
        recorder.close()


def test_follow_without_auto_takeoff_flag_never_engages_sequencing(tmp_path):
    """Regular Follow (no auto_takeoff in the payload - e.g. the operator
    manually arms first, then picks Follow once already airborne) must
    behave exactly as before this feature - no held frames, no takeoff
    command ever sent."""
    with _build_connected_orchestrator(tmp_path) as (orchestrator, recorder, conn):
        orchestrator.mavlink.telemetry.fc_mode = "GUIDED"

        orchestrator._on_mode_command({"mode": "follow"})

        assert not orchestrator.auto_takeoff.is_active
        assert orchestrator.auto_takeoff.phase == AutoTakeoffPhase.IDLE
        conn.mav.command_long_send.assert_not_called()
        recorder.close()
