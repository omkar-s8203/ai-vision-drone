"""Companion orchestrator - wires vision, tracking, guidance, MAVLink,
comms, and safety into the single asyncio process described in the
project plan (docs plan section 0 / M15). Two modes:

- "sim": SyntheticCamera + a synthetic moving target + MockFlightController,
  runs entirely on a dev machine, no hardware required (docs plan M13).
- "hardware": Picamera2IMX500Camera + real serial MAVLink connection - only
  runs on a Raspberry Pi with the AI Camera and a wired flight controller.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from companion.comms.transport import WebSocketTransport
from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachInputs, ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.logging_.session_recorder import SessionRecorder
from companion.logging_.setup import configure_logging
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.contact_sensor import ContactSensor, NullContactSensor
from companion.safety.supervisor import SafetySupervisor, SupervisorInputs, SupervisorState
from companion.safety.watchdog import HeartbeatWatchdog, SystemdWatchdog
from companion.tracking.base import Tracker
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState, TrackingStateMachine
from companion.tracking.target_selector import select_target
from companion.vision.camera import CameraBase
from companion.vision.detector import BBox, Detection, DetectorBase

log = logging.getLogger(__name__)

MODE_COMMAND_MAP = {
    "idle": SupervisorState.IDLE,
    "tracking": SupervisorState.TRACKING,
    "follow": SupervisorState.FOLLOWING,
    "approach": SupervisorState.APPROACHING,
}

AI_GUIDANCE_MODE_NAME = "GUIDED"


class CompanionOrchestrator:
    def __init__(
        self,
        camera: CameraBase,
        detector: DetectorBase,
        tracker: Tracker,
        distance_estimator: DistanceEstimator,
        follow_controller: FollowController,
        approach_controller: ApproachTestController,
        mavlink: MavlinkBridge,
        rc_monitor: RcOverrideMonitor,
        supervisor: SafetySupervisor,
        watchdog: HeartbeatWatchdog,
        link: GroundStationLink,
        recorder: SessionRecorder,
        contact_sensor: Optional[ContactSensor] = None,
        reacquire_timeout_s: float = 2.0,
    ) -> None:
        self.camera = camera
        self.detector = detector
        self.state_machine = TrackingStateMachine(tracker, reacquire_timeout_s)
        self.distance_estimator = distance_estimator
        self.follow = follow_controller
        self.approach = approach_controller
        self.mavlink = mavlink
        self.rc_monitor = rc_monitor
        self.supervisor = supervisor
        self.watchdog = watchdog
        self.link = link
        self.recorder = recorder
        self.contact_sensor = contact_sensor or NullContactSensor()

        self.requested_mode = SupervisorState.IDLE
        self._pending_selection: Optional[BBox] = None
        self._last_frame_ts: Optional[float] = None

        self.link.on_target_selected(self._on_target_selected)
        self.link.on_mode_command(self._on_mode_command)
        self.link.on_abort(self._on_abort)

    def _on_target_selected(self, payload: dict) -> None:
        self._pending_selection = BBox(
            x=payload["x"], y=payload["y"], w=payload["w"], h=payload["h"]
        )

    def _on_mode_command(self, payload: dict) -> None:
        mode = MODE_COMMAND_MAP.get(payload.get("mode", "idle"), SupervisorState.IDLE)
        self.requested_mode = mode
        if mode == SupervisorState.APPROACHING:
            self.approach.start()
        else:
            self.approach.stop()
        self.recorder.record("mode_command", mode=mode.name)

    def _on_abort(self, payload: dict) -> None:
        self.requested_mode = SupervisorState.IDLE
        self.approach.stop()
        self.state_machine.stop()
        self.recorder.record("abort", reason=payload.get("reason"))

    async def start(self) -> None:
        await self.link.start()
        if not self.mavlink.is_connected:
            self.mavlink.connect()
        asyncio.create_task(
            self.mavlink.run(on_message=lambda _msg: self.watchdog.beat("mavlink"))
        )
        await self._perception_loop()

    async def process_frame(self, frame) -> dict:
        """Runs one full perception -> tracking -> guidance -> safety cycle
        for a single frame. Split out from `_perception_loop` so tests can
        drive it deterministically without a real event loop."""
        self.watchdog.beat("camera")
        detections = self.detector.parse(frame.raw_detection_output, frame.ts)

        if self._pending_selection is not None and self.state_machine.state == TrackingState.IDLE:
            det = select_target(detections, self._pending_selection)
            if det is not None:
                self.state_machine.start(frame.ts, det)
            self._pending_selection = None

        tracking_state = self.state_machine.update(frame.ts, detections)
        self.watchdog.beat("tracker")

        distance_m = None
        if self.state_machine.target is not None:
            t = self.state_machine.target
            det_for_distance = Detection(
                bbox=t.bbox, score=t.confidence, class_id=t.class_id,
                class_name=t.class_name, frame_ts=frame.ts,
            )
            distance_m, _source = self.distance_estimator.estimate(det_for_distance)

        rc_override = self.rc_monitor.is_overriding(self.mavlink.telemetry.rc_channels)
        comms_alive = self.link.is_connected
        if comms_alive:
            self.watchdog.beat("comms")

        decision = self.supervisor.evaluate(
            SupervisorInputs(
                fc_mode=self.mavlink.telemetry.fc_mode,
                ai_guidance_mode_name=AI_GUIDANCE_MODE_NAME,
                rc_override_active=rc_override,
                tracking_state=tracking_state,
                comms_alive=comms_alive,
                requested_state=self.requested_mode,
            )
        )

        dt = 0.0 if self._last_frame_ts is None else max(0.0, frame.ts - self._last_frame_ts)
        self._last_frame_ts = frame.ts

        command = None
        if decision.state == SupervisorState.FOLLOWING and self.state_machine.target is not None:
            command = self.follow.compute(
                self.state_machine.target, distance_m, frame.width, frame.height, dt
            )
        elif decision.state == SupervisorState.APPROACHING:
            result = self.approach.update(
                ApproachInputs(
                    distance_m=distance_m,
                    contact_detected=self.contact_sensor.is_contact(),
                    target_tracked=tracking_state == TrackingState.TRACKING,
                    comms_alive=comms_alive,
                    rc_override_active=rc_override,
                    geofence_breached=False,
                )
            )
            command = result.command
            if result.abort_reason:
                self.recorder.record("approach_abort", reason=result.abort_reason)

        sent = False
        if command is not None and decision.guidance_allowed:
            sent = self.mavlink.send_velocity_setpoint(
                command.vx_mps, command.vy_mps, command.vz_mps, command.yaw_rate_rads,
                guidance_allowed=True,
            )
            self.recorder.record(
                "guidance_command",
                vx=command.vx_mps, vy=command.vy_mps, vz=command.vz_mps,
                yaw_rate=command.yaw_rate_rads,
            )

        await self.link.send_tracking_update(
            {
                "state": tracking_state.name,
                "target_id": self.state_machine.target.target_id if self.state_machine.target else None,
                "confidence": self.state_machine.target.confidence if self.state_machine.target else None,
                "distance_m": distance_m,
                "supervisor_state": decision.state.name,
                "guidance_allowed": decision.guidance_allowed,
                "guidance_reason": decision.reason,
            }
        )

        return {
            "tracking_state": tracking_state,
            "supervisor_decision": decision,
            "command_sent": sent,
        }

    async def _perception_loop(self) -> None:
        async for frame in self.camera.frames():
            await self.process_frame(frame)


SIM_FC_UDP_PORT = 14550
SIM_BRIDGE_UDP_PORT = 14551


def build_sim_orchestrator() -> tuple[CompanionOrchestrator, "object"]:
    """Builds a fully self-contained sim-mode stack: synthetic camera/target
    and an embedded MockFlightController, so `python -m companion.main`
    (COMPANION_MODE=sim) runs end-to-end with no external SITL/hardware -
    see docs plan M13. Returns (orchestrator, mock_fc); the caller is
    responsible for starting mock_fc.run() as a background task.
    """
    from sim.mock_fc import MockFlightController
    from sim.synthetic_target import SyntheticTargetGenerator
    from companion.vision.camera import SyntheticCamera
    from companion.vision.detector import PassthroughDetector

    hardware_cfg = load_yaml("hardware.yaml")
    network_cfg = load_yaml("network.yaml")
    follow_cfg = load_yaml("follow_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")

    generator = SyntheticTargetGenerator(
        image_width=hardware_cfg["camera"]["width"], image_height=hardware_cfg["camera"]["height"]
    )
    camera = SyntheticCamera(
        width=hardware_cfg["camera"]["width"],
        height=hardware_cfg["camera"]["height"],
        target_fps=hardware_cfg["camera"]["target_fps"],
        detection_source=generator.detections_at,
    )
    detector = PassthroughDetector()
    tracker = IouKalmanTracker()
    distance_estimator = DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg))
    follow_controller = FollowController(follow_cfg)
    approach_controller = ApproachTestController(approach_cfg)

    mock_fc = MockFlightController(f"udpin:127.0.0.1:{SIM_FC_UDP_PORT}")
    mock_fc.set_mode("GUIDED")
    mock_fc.set_armed(True)

    mavlink = MavlinkBridge(f"udpin:127.0.0.1:{SIM_BRIDGE_UDP_PORT}")
    mavlink.connect()
    mavlink.prime_udp_peer("127.0.0.1", SIM_FC_UDP_PORT)

    rc_monitor = RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"])
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    supervisor = SafetySupervisor(watchdog)
    transport = WebSocketTransport(network_cfg["ws_host"], network_cfg["ws_port"])
    link = GroundStationLink(transport)
    recorder = SessionRecorder(Path("companion/logs/sessions"))

    orchestrator = CompanionOrchestrator(
        camera=camera, detector=detector, tracker=tracker,
        distance_estimator=distance_estimator, follow_controller=follow_controller,
        approach_controller=approach_controller, mavlink=mavlink, rc_monitor=rc_monitor,
        supervisor=supervisor, watchdog=watchdog, link=link, recorder=recorder,
    )
    return orchestrator, mock_fc


def build_hardware_orchestrator() -> CompanionOrchestrator:
    from companion.vision.camera import Picamera2IMX500Camera
    from companion.vision.detector import IMX500Detector

    hardware_cfg = load_yaml("hardware.yaml")
    network_cfg = load_yaml("network.yaml")
    follow_cfg = load_yaml("follow_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")

    camera = Picamera2IMX500Camera(
        width=hardware_cfg["camera"]["width"],
        height=hardware_cfg["camera"]["height"],
        target_fps=hardware_cfg["camera"]["target_fps"],
    )
    detector = IMX500Detector(class_names={0: "person", 2: "car"})
    tracker = IouKalmanTracker()
    distance_estimator = DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg))
    follow_controller = FollowController(follow_cfg)
    approach_controller = ApproachTestController(approach_cfg)
    mavlink = MavlinkBridge(hardware_cfg["mavlink"]["connection"])
    rc_monitor = RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"])
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    supervisor = SafetySupervisor(watchdog)
    transport = WebSocketTransport(network_cfg["ws_host"], network_cfg["ws_port"])
    link = GroundStationLink(transport)
    recorder = SessionRecorder(Path("/var/log/ai-vision-drone/sessions"))

    return CompanionOrchestrator(
        camera=camera, detector=detector, tracker=tracker,
        distance_estimator=distance_estimator, follow_controller=follow_controller,
        approach_controller=approach_controller, mavlink=mavlink, rc_monitor=rc_monitor,
        supervisor=supervisor, watchdog=watchdog, link=link, recorder=recorder,
    )


async def _amain() -> None:
    mode = os.environ.get("COMPANION_MODE", "sim")
    configure_logging(Path("companion/logs"))
    log.info("Starting companion orchestrator in %s mode", mode)

    background_tasks: list[asyncio.Task] = []
    if mode == "sim":
        orchestrator, mock_fc = build_sim_orchestrator()
        background_tasks.append(asyncio.create_task(mock_fc.run(rate_hz=10.0)))
    else:
        orchestrator = build_hardware_orchestrator()

    watchdog_task = asyncio.create_task(SystemdWatchdog().run())
    background_tasks.append(watchdog_task)
    try:
        await orchestrator.start()
    finally:
        for task in background_tasks:
            task.cancel()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
