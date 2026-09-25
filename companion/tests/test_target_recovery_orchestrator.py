from contextlib import contextmanager
from unittest.mock import patch

import pytest

from companion.comms.protocol import Envelope
from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.guidance.target_recovery import TargetRecoveryController
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor, SupervisorState
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
from companion.vision.camera import Frame
from companion.vision.detector import BBox, Detection, PassthroughDetector

# Fast, deterministic timings distinct from the real target_recovery.yaml
# defaults, so these tests don't need to wait 60 real seconds.
FAST_RECOVERY_LIMITS = {
    "search_timeout_s": 0.2,
    "search_yaw_rate_rads": 0.3,
    "sweep_half_period_s": 10.0,  # long enough that direction never flips mid-test
    "low_battery_pct_threshold": 20,
    "assumed_return_speed_mps": 5.0,
    "assumed_max_flight_time_s": 900,
    "rtl_safety_margin": 1.5,
}


@contextmanager
def _build_orchestrator(tmp_path, recovery_limits=None):
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    transport = FakeTransport(connected=True)
    link = GroundStationLink(transport)
    recorder = SessionRecorder(tmp_path / "session")
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14780")
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
            recovery_controller=TargetRecoveryController(recovery_limits or FAST_RECOVERY_LIMITS),
            reacquire_timeout_s=0.1,  # fast, so a short "no detections" loop reaches TARGET_LOST quickly
        )
        yield orchestrator, recorder, conn, transport


def _person(ts: float) -> Detection:
    return Detection(bbox=BBox(600, 300, 80, 160), score=0.9, class_id=0, class_name="person", frame_ts=ts)


async def _engage_follow(orchestrator):
    """Select a target and switch to Follow, with the FC already in GUIDED
    and subsystems healthy - the minimum needed for guidance_allowed."""
    orchestrator.mavlink.telemetry.fc_mode = "GUIDED"
    orchestrator.watchdog.beat("mavlink")
    orchestrator.watchdog.beat("rc_channels")
    orchestrator._on_target_selected({"x": 640.0, "y": 380.0, "point": True})
    await orchestrator.process_frame(Frame(ts=0.0, width=1280, height=720, raw_detection_output=[_person(0.0)]))
    orchestrator._on_mode_command({"mode": "follow"})
    assert orchestrator.state_machine.state == TrackingState.TRACKING


@pytest.mark.asyncio
async def test_target_loss_during_follow_engages_search_with_a_yaw_only_command(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)
        conn.mav.set_position_target_local_ned_send.reset_mock()

        # Long enough with no detections to pass the tracker's own short
        # REACQUIRE window and reach TARGET_LOST, but short of the fast
        # search_timeout_s=0.2 configured above.
        ts = 0.1
        for _ in range(6):
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05

        assert orchestrator.state_machine.state == TrackingState.TARGET_LOST
        assert orchestrator.recovery.is_active is True
        assert conn.mav.set_position_target_local_ned_send.called
        # vx/vy/vz all zero, only yaw_rate nonzero - a pure sweep, not motion.
        # Positional args: time_boot_ms, target_system, target_component, frame,
        # type_mask, x, y, z, vx, vy, vz, afx, afy, afz, yaw, yaw_rate.
        call_args = conn.mav.set_position_target_local_ned_send.call_args[0]
        vx, vy, vz, yaw_rate = call_args[8], call_args[9], call_args[10], call_args[15]
        assert vx == 0.0
        assert vy == 0.0
        assert vz == 0.0
        assert yaw_rate != 0.0
        recorder.close()


@pytest.mark.asyncio
async def test_target_reacquired_during_search_cancels_recovery_and_resumes_follow(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)

        ts = 0.1
        for _ in range(6):
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05
        assert orchestrator.recovery.is_active is True

        # Isolates this test from the separately-tested appearance-rematch
        # mechanism (test_appearance_reacquire.py) - directly simulating
        # "the target is back" the way any reacquisition path (appearance
        # match or otherwise) would leave tracking state, so this test
        # covers the recovery controller's own found/cancel wiring only.
        orchestrator.state_machine.start(ts, _person(ts))
        await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[_person(ts)]))

        assert orchestrator.recovery.is_active is False
        assert orchestrator.requested_mode == SupervisorState.FOLLOWING
        recorder.close()


@pytest.mark.asyncio
async def test_search_timeout_with_healthy_battery_triggers_rtl(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)
        orchestrator.mavlink.telemetry.armed = True  # the Pi only RTLs an aircraft it is flying
        orchestrator.mavlink.telemetry.battery_remaining_pct = 80
        orchestrator.mavlink.telemetry.home_lat = 37.7749
        orchestrator.mavlink.telemetry.home_lon = -122.4194
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194

        ts = 0.1
        for _ in range(10):  # comfortably past the fast 0.2s search_timeout_s
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05

        conn.mav.set_mode_send.assert_any_call(1, 1, 6)  # RTL = 6
        assert orchestrator.requested_mode == SupervisorState.IDLE
        assert orchestrator.recovery.is_active is False
        recorder.close()


@pytest.mark.asyncio
async def test_search_timeout_with_low_battery_and_far_distance_requests_landing_not_rtl(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)
        orchestrator.mavlink.telemetry.battery_remaining_pct = 5
        orchestrator.mavlink.telemetry.home_lat = 0.0
        orchestrator.mavlink.telemetry.home_lon = 0.0
        orchestrator.mavlink.telemetry.lat = 1.0  # ~111km away
        orchestrator.mavlink.telemetry.lon = 0.0

        ts = 0.1
        for _ in range(10):
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05

        assert conn.mav.set_mode_send.call_args_list == [] or all(
            call.args[2] != 6 for call in conn.mav.set_mode_send.call_args_list
        )  # RTL (6) must NOT have been triggered
        assert orchestrator.recovery.is_active is True  # awaiting operator confirmation

        land_requests = [
            Envelope.from_json(raw) for raw in transport.sent
            if Envelope.from_json(raw).type == "land_confirmation_request"
        ]
        assert len(land_requests) == 1
        assert land_requests[0].payload["battery_remaining_pct"] == 5
        assert land_requests[0].payload["distance_to_home_m"] > 100_000
        recorder.close()


@pytest.mark.asyncio
async def test_operator_approving_landing_sets_land_mode(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)
        orchestrator.mavlink.telemetry.battery_remaining_pct = 5
        orchestrator.mavlink.telemetry.home_lat = 0.0
        orchestrator.mavlink.telemetry.home_lon = 0.0
        orchestrator.mavlink.telemetry.lat = 1.0
        orchestrator.mavlink.telemetry.lon = 0.0
        ts = 0.1
        for _ in range(10):
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05
        assert orchestrator.recovery.is_active is True

        orchestrator._on_land_confirmation_response({"approved": True})

        conn.mav.set_mode_send.assert_any_call(1, 1, 9)  # LAND = 9
        assert orchestrator.requested_mode == SupervisorState.IDLE
        assert orchestrator.recovery.is_active is False
        recorder.close()


@pytest.mark.asyncio
async def test_mode_command_away_from_follow_cancels_an_active_search(tmp_path):
    """A real bug found in a code-review audit: only _on_abort() cancelled
    an in-progress target-loss search - explicitly commanding away from
    Follow/Orbit (e.g. selecting "Normal RC"/idle in the app) left the
    yaw-sweep search running to completion on its own timer, deaf to the
    operator's own mode change."""
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)

        ts = 0.1
        for _ in range(6):
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05
        assert orchestrator.recovery.is_active is True

        orchestrator._on_mode_command({"mode": "idle"})

        assert orchestrator.recovery.is_active is False
        recorder.close()


@pytest.mark.asyncio
async def test_rtl_is_suppressed_while_pilot_has_rc_override(tmp_path):
    """A real bug found in a code-review audit: RTL_TRIGGERED fired
    mavlink.set_mode("RTL") unconditionally, even if the pilot had already
    taken RC stick override mid-search - contradicting "RC override always
    takes precedence" (docs/safety-case.md). The pilot is already flying
    manually at that point; an autonomous RTL has nothing useful to
    override and would yank control away from them instead."""
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)
        orchestrator.mavlink.telemetry.battery_remaining_pct = 80
        orchestrator.mavlink.telemetry.home_lat = 37.7749
        orchestrator.mavlink.telemetry.home_lon = -122.4194
        orchestrator.mavlink.telemetry.lat = 37.7749
        orchestrator.mavlink.telemetry.lon = -122.4194
        orchestrator.mavlink.telemetry.rc_channels = {1: 1900}  # roll stick deflected - override

        ts = 0.1
        for _ in range(10):  # comfortably past the fast 0.2s search_timeout_s
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05

        assert all(call.args[2] != 6 for call in conn.mav.set_mode_send.call_args_list)  # RTL (6) never sent
        recorder.close()


@pytest.mark.asyncio
async def test_operator_denying_landing_does_not_land(tmp_path):
    with _build_orchestrator(tmp_path) as (orchestrator, recorder, conn, transport):
        await _engage_follow(orchestrator)
        orchestrator.mavlink.telemetry.battery_remaining_pct = 5
        orchestrator.mavlink.telemetry.home_lat = 0.0
        orchestrator.mavlink.telemetry.home_lon = 0.0
        orchestrator.mavlink.telemetry.lat = 1.0
        orchestrator.mavlink.telemetry.lon = 0.0
        ts = 0.1
        for _ in range(10):
            await orchestrator.process_frame(Frame(ts=ts, width=1280, height=720, raw_detection_output=[]))
            ts += 0.05
        assert orchestrator.recovery.is_active is True

        orchestrator._on_land_confirmation_response({"approved": False})

        assert all(call.args[2] != 9 for call in conn.mav.set_mode_send.call_args_list)  # LAND never sent
        assert orchestrator.requested_mode == SupervisorState.IDLE
        assert orchestrator.recovery.is_active is False
        recorder.close()
