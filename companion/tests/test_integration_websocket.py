import asyncio
import json
from typing import Optional

import pytest
import websockets

from companion.comms.protocol import Envelope, MessageType, make_envelope
from companion.comms.transport import WebSocketTransport
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
from companion.safety.supervisor import SafetySupervisor, SupervisorState
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import wait_until
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
from companion.vision.camera import Frame
from companion.vision.detector import PassthroughDetector
from sim.mock_fc import MockFlightController
from sim.synthetic_target import SyntheticTargetGenerator

WS_PORT = 18765
FC_PORT = 14730
BRIDGE_PORT = 14731


async def recv_envelope_of_type(client, msg_type: str, timeout: float = 3.0) -> Envelope:
    """process_frame() broadcasts several message types every frame
    (tracking_update, detections_update, telemetry, health) - this drains
    the socket until the one we actually care about shows up, rather than
    assuming it's the very next message. Returns the *latest* matching
    envelope, not just the first: an earlier call in the same test may have
    stopped as soon as it matched its own (different) target type, leaving
    older same-type messages from a now-superseded frame still queued
    behind it - returning only the first match would silently hand back
    stale data instead of the state produced by the most recent
    process_frame() call."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    latest: Optional[Envelope] = None
    while True:
        # Once we've seen one match, only wait briefly for anything newer
        # already in flight rather than blocking for the full timeout -
        # this keeps the "get the freshest one" behavior cheap.
        remaining = 0.15 if latest is not None else max(0.01, deadline - loop.time())
        try:
            raw = await asyncio.wait_for(client.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            if latest is not None:
                return latest
            raise AssertionError(f"no {msg_type} message received within {timeout}s")
        envelope = Envelope.from_json(raw)
        if envelope.type == msg_type:
            latest = envelope


@pytest.mark.asyncio
async def test_full_operator_session_over_a_real_websocket(tmp_path):
    """Every other integration test in this suite talks to the
    orchestrator through FakeTransport - real Python method calls dispatch
    handlers directly, with no JSON envelope ever actually serialized or
    parsed. That leaves the one thing an Android app (or any other real
    client) actually depends on - the wire protocol itself - completely
    unverified by automated tests. This test is a stand-in operator: a
    real `websockets` client connects to a real WebSocketTransport server
    and drives a full session (select a target, switch to Follow, arm,
    change flight mode, abort) using the exact JSON envelopes
    companion/comms/protocol.py defines, over a real socket, against a
    real (mock) flight controller on the other end of a real MAVLink link.
    """
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")

    mock_fc = MockFlightController(f"udpin:127.0.0.1:{FC_PORT}")
    mock_fc.set_mode("GUIDED")
    fc_task = asyncio.create_task(mock_fc.run(rate_hz=20.0))

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{BRIDGE_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", FC_PORT)
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    mavlink_task = asyncio.create_task(mavlink.run(on_message=lambda _msg: watchdog.beat("mavlink")))

    generator = SyntheticTargetGenerator(image_width=1280, image_height=720, path_amplitude_px=0.0)
    transport = WebSocketTransport("127.0.0.1", WS_PORT)
    link = GroundStationLink(transport)
    recorder = SessionRecorder(tmp_path)

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

    await link.start()
    seq = 0

    def send(client_ws, msg_type: str, payload: dict):
        nonlocal seq
        seq += 1
        return client_ws.send(make_envelope(msg_type, payload, seq).to_json())

    try:
        await wait_until(lambda: mavlink.telemetry.fc_mode == "GUIDED", timeout=3.0)
        watchdog.beat("camera")
        watchdog.beat("tracker")

        async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as client:
            await wait_until(lambda: transport.has_clients, timeout=2.0)

            # 1. Select the target over the real wire (a real target_select
            # envelope, not a Python method call).
            initial_bbox = generator.detections_at(0.0)[0].bbox
            await send(client, MessageType.TARGET_SELECT, {
                "x": initial_bbox.x, "y": initial_bbox.y, "w": initial_bbox.w, "h": initial_bbox.h,
            })
            await asyncio.sleep(0.05)  # let the server's receive loop dispatch it
            frame = Frame(ts=0.0, width=1280, height=720, raw_detection_output=generator.detections_at(0.0))
            watchdog.beat("camera")
            watchdog.beat("tracker")
            await orchestrator.process_frame(frame)

            assert orchestrator.state_machine.state == TrackingState.TRACKING
            tracking_msg = await recv_envelope_of_type(client, MessageType.TRACKING_UPDATE)
            assert tracking_msg.payload["state"] == "TRACKING"

            # 2. Switch to Follow mode over the real wire.
            await send(client, MessageType.MODE_COMMAND, {"mode": "follow", "follow_separation_m": 8.0})
            await asyncio.sleep(0.05)
            assert orchestrator.requested_mode == SupervisorState.FOLLOWING
            assert orchestrator.follow.limits["target_separation_m"] == 8.0

            # 3. Arm over the real wire - must reach the real (mock) FC over
            # real MAVLink, not just flip a local flag.
            assert mock_fc.armed is False
            await send(client, MessageType.ARM_COMMAND, {"armed": True})
            await asyncio.sleep(0.05)
            await wait_until(lambda: mock_fc.armed is True, timeout=2.0)

            # 4. Change flight mode over the real wire.
            await send(client, MessageType.SET_FLIGHT_MODE, {"mode": "RTL"})
            await asyncio.sleep(0.05)
            await wait_until(lambda: mock_fc.fc_mode == "RTL", timeout=2.0)

            # 5. Abort over the real wire - guidance mode drops, tracking stops.
            await send(client, MessageType.ABORT, {"reason": "operator"})
            await asyncio.sleep(0.05)
            assert orchestrator.requested_mode == SupervisorState.IDLE
            assert orchestrator.state_machine.state == TrackingState.IDLE

            # A live health message really did arrive over the socket too -
            # proves the Pi -> Android direction isn't just theoretical.
            watchdog.beat("camera")
            watchdog.beat("tracker")
            await orchestrator.process_frame(
                Frame(ts=0.1, width=1280, height=720, raw_detection_output=[])
            )
            health_msg = await recv_envelope_of_type(client, MessageType.HEALTH)
            assert health_msg.payload["mavlink_ok"] is True

            # 6. A real geofence breach on the (mock) FC really does reach
            # the Android side over the wire in the telemetry message, not
            # just internally on orchestrator.mavlink.telemetry (see
            # test_approach_orchestrator.py for that half of the proof).
            mock_fc.set_fence_state(enabled=True, breached=True)
            await wait_until(lambda: mavlink.telemetry.fence_breached is True, timeout=2.0)
            watchdog.beat("camera")
            watchdog.beat("tracker")
            await orchestrator.process_frame(
                Frame(ts=0.2, width=1280, height=720, raw_detection_output=[])
            )
            telemetry_msg = await recv_envelope_of_type(client, MessageType.TELEMETRY)
            assert telemetry_msg.payload["fence_enabled"] is True
            assert telemetry_msg.payload["fence_breached"] is True
    finally:
        await link.stop()
        fc_task.cancel()
        mavlink_task.cancel()
        recorder.close()
        await asyncio.gather(fc_task, mavlink_task, return_exceptions=True)
