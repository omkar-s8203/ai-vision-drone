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
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from companion.comms.transport import WebSocketTransport
from companion.comms.video_recorder import VideoRecorder
from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachInputs, ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.logging_.session_recorder import SessionRecorder
from companion.logging_.setup import configure_logging
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.contact_sensor import ContactSensor, NullContactSensor
from companion.safety.proximity_guard import check_proximity
from companion.safety.supervisor import (
    REQUIRED_SUBSYSTEMS,
    SafetySupervisor,
    SupervisorInputs,
    SupervisorState,
)
from companion.safety.watchdog import HeartbeatWatchdog, SystemdWatchdog
from companion.tracking.base import Tracker
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState, TrackingStateMachine
from companion.tracking.target_selector import select_target, select_target_at_point
from companion.vision.camera import CameraBase
from companion.vision.detector import BBox, Detection, DetectorBase

if TYPE_CHECKING:
    from companion.comms.video_pipeline import VideoPipeline

log = logging.getLogger(__name__)

MODE_COMMAND_MAP = {
    "idle": SupervisorState.IDLE,
    "tracking": SupervisorState.TRACKING,
    "follow": SupervisorState.FOLLOWING,
    "orbit": SupervisorState.ORBITING,
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
        orbit_controller: OrbitController,
        approach_controller: ApproachTestController,
        mavlink: MavlinkBridge,
        rc_monitor: RcOverrideMonitor,
        supervisor: SafetySupervisor,
        watchdog: HeartbeatWatchdog,
        link: GroundStationLink,
        recorder: SessionRecorder,
        contact_sensor: Optional[ContactSensor] = None,
        video_pipeline: Optional["VideoPipeline"] = None,
        video_recorder: Optional[VideoRecorder] = None,
        reacquire_timeout_s: float = 2.0,
        min_obstacle_distance_m: float = 2.0,
    ) -> None:
        self.camera = camera
        self.detector = detector
        self.state_machine = TrackingStateMachine(tracker, reacquire_timeout_s)
        self.distance_estimator = distance_estimator
        self.follow = follow_controller
        self.orbit = orbit_controller
        self.approach = approach_controller
        self.min_obstacle_distance_m = min_obstacle_distance_m
        self.mavlink = mavlink
        self.rc_monitor = rc_monitor
        self.supervisor = supervisor
        self.watchdog = watchdog
        self.link = link
        self.recorder = recorder
        self.contact_sensor = contact_sensor or NullContactSensor()
        self.video_pipeline = video_pipeline
        self.video_recorder = video_recorder

        self.requested_mode = SupervisorState.IDLE
        self._pending_selection: Optional[tuple] = None  # ("bbox", BBox) or ("point", x, y)
        self._last_frame_ts: Optional[float] = None
        self._recent_frame_ts: list[float] = []
        self._frame_size: Optional[tuple[int, int]] = None  # (width, height) of the latest frame

        self.link.on_target_selected(self._on_target_selected)
        self.link.on_mode_command(self._on_mode_command)
        self.link.on_abort(self._on_abort)
        self.link.on_arm_command(self._on_arm_command)
        self.link.on_set_flight_mode(self._on_set_flight_mode)
        self.link.on_record_command(self._on_record_command)
        if self.video_pipeline is not None:
            self.link.on_webrtc_offer(self._on_webrtc_offer_sync)

    def _on_webrtc_offer_sync(self, payload: dict) -> None:
        asyncio.create_task(self._on_webrtc_offer(payload))

    async def _on_webrtc_offer(self, payload: dict) -> None:
        assert self.video_pipeline is not None
        try:
            answer_sdp, answer_type = await self.video_pipeline.handle_offer(
                payload["sdp"], payload["sdp_type"]
            )
            await self.link.send_webrtc_answer(answer_sdp, answer_type)
        except Exception:
            log.exception("Failed to handle WebRTC offer")

    def _on_target_selected(self, payload: dict) -> None:
        if payload.get("point"):
            self._pending_selection = ("point", payload["x"], payload["y"])
        else:
            self._pending_selection = (
                "bbox",
                BBox(x=payload["x"], y=payload["y"], w=payload["w"], h=payload["h"]),
            )

    def _on_mode_command(self, payload: dict) -> None:
        mode = MODE_COMMAND_MAP.get(payload.get("mode", "idle"), SupervisorState.IDLE)
        self.requested_mode = mode
        if mode == SupervisorState.APPROACHING:
            self.approach.start()
        else:
            self.approach.stop()
        separation = payload.get("follow_separation_m")
        if separation is not None:
            self.follow.limits["target_separation_m"] = float(separation)
        altitude = payload.get("follow_altitude_m")
        if altitude is not None:
            self.follow.limits["target_altitude_m"] = float(altitude)
        orbit_radius = payload.get("orbit_radius_m")
        if orbit_radius is not None:
            self.orbit.limits["orbit_radius_m"] = float(orbit_radius)
        orbit_altitude = payload.get("orbit_altitude_m")
        if orbit_altitude is not None:
            self.orbit.limits["target_altitude_m"] = float(orbit_altitude)
        self.recorder.record(
            "mode_command",
            mode=mode.name,
            follow_separation_m=separation,
            follow_altitude_m=altitude,
            orbit_radius_m=orbit_radius,
            orbit_altitude_m=orbit_altitude,
        )

    def _on_abort(self, payload: dict) -> None:
        self.requested_mode = SupervisorState.IDLE
        self.approach.stop()
        self.state_machine.stop()
        self.recorder.record("abort", reason=payload.get("reason"))

    def _on_arm_command(self, payload: dict) -> None:
        """Arm/disarm is an administrative FC command, not a guidance
        setpoint - it goes straight to the FC like a standard GCS would send
        it, bypassing the Safety Supervisor's guidance gate (that gate only
        concerns itself with velocity setpoints during active AI guidance)."""
        armed = bool(payload.get("armed", False))
        self.mavlink.arm(armed)
        self.recorder.record("arm_command", armed=armed)

    def _on_set_flight_mode(self, payload: dict) -> None:
        mode = str(payload.get("mode", ""))
        ok = self.mavlink.set_mode(mode)
        self.recorder.record("set_flight_mode", mode=mode, accepted=ok)

    def _on_record_command(self, payload: dict) -> None:
        asyncio.create_task(self._handle_record_command(bool(payload.get("recording", False))))

    async def _handle_record_command(self, want_recording: bool) -> None:
        if self.video_recorder is None:
            return
        if want_recording and not self.video_recorder.is_recording:
            width, height = self._frame_size or (
                self.camera.width if hasattr(self.camera, "width") else 1280,
                self.camera.height if hasattr(self.camera, "height") else 720,
            )
            path = self.video_recorder.start(width=width, height=height)
            self.recorder.record("record_start", path=str(path))
        elif not want_recording and self.video_recorder.is_recording:
            path = self.video_recorder.stop()
            self.recorder.record("record_stop", path=str(path) if path else None)
        await self.link.send_recording_state(
            {
                "recording": self.video_recorder.is_recording,
                "duration_s": self.video_recorder.duration_s,
            }
        )

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
        self._recent_frame_ts.append(time.monotonic())
        if len(self._recent_frame_ts) > 30:
            self._recent_frame_ts.pop(0)
        self._frame_size = (frame.width, frame.height)
        if self.video_recorder is not None and self.video_recorder.is_recording:
            self.video_recorder.write(self.camera.get_latest_frame())
        detections = self.detector.parse(frame.raw_detection_output, frame.ts)

        if self._pending_selection is not None and self.state_machine.state == TrackingState.IDLE:
            if self._pending_selection[0] == "point":
                _, px, py = self._pending_selection
                det = select_target_at_point(detections, px, py)
            else:
                _, bbox = self._pending_selection
                det = select_target(detections, bbox)
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

        obstacle_alert = check_proximity(detections, self.distance_estimator, self.min_obstacle_distance_m)
        if obstacle_alert is not None:
            self.recorder.record(
                "obstacle_alert", class_name=obstacle_alert.class_name, distance_m=obstacle_alert.distance_m
            )

        decision = self.supervisor.evaluate(
            SupervisorInputs(
                fc_mode=self.mavlink.telemetry.fc_mode,
                ai_guidance_mode_name=AI_GUIDANCE_MODE_NAME,
                rc_override_active=rc_override,
                tracking_state=tracking_state,
                comms_alive=comms_alive,
                requested_state=self.requested_mode,
                obstacle_alert=obstacle_alert,
            )
        )

        dt = 0.0 if self._last_frame_ts is None else max(0.0, frame.ts - self._last_frame_ts)
        self._last_frame_ts = frame.ts

        command = None
        if decision.state == SupervisorState.FOLLOWING and self.state_machine.target is not None:
            command = self.follow.compute(
                self.state_machine.target,
                distance_m,
                frame.width,
                frame.height,
                dt,
                current_altitude_m=self.mavlink.telemetry.alt_m,
            )
        elif decision.state == SupervisorState.ORBITING and self.state_machine.target is not None:
            command = self.orbit.compute(
                self.state_machine.target,
                distance_m,
                frame.width,
                frame.height,
                dt,
                current_altitude_m=self.mavlink.telemetry.alt_m,
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

        target = self.state_machine.target
        await self.link.send_tracking_update(
            {
                "state": tracking_state.name,
                "target_id": target.target_id if target else None,
                "confidence": target.confidence if target else None,
                "bbox": (
                    {"x": target.bbox.x, "y": target.bbox.y, "w": target.bbox.w, "h": target.bbox.h}
                    if target
                    else None
                ),
                "image_width": frame.width,
                "image_height": frame.height,
                "distance_m": distance_m,
                "supervisor_state": decision.state.name,
                "guidance_allowed": decision.guidance_allowed,
                "guidance_reason": decision.reason,
            }
        )
        await self.link.send_detections_update(
            {
                "image_width": frame.width,
                "image_height": frame.height,
                "detections": [
                    {
                        "bbox": {"x": d.bbox.x, "y": d.bbox.y, "w": d.bbox.w, "h": d.bbox.h},
                        "class_name": d.class_name,
                        "score": d.score,
                    }
                    for d in detections
                ],
            }
        )
        await self.link.send_telemetry(self._build_telemetry_payload())
        await self.link.send_health(self._build_health_payload())

        return {
            "tracking_state": tracking_state,
            "supervisor_decision": decision,
            "command_sent": sent,
        }

    def _build_telemetry_payload(self) -> dict:
        t = self.mavlink.telemetry
        return {
            "fc_mode": t.fc_mode,
            "armed": t.armed,
            "lat": t.lat,
            "lon": t.lon,
            "alt_m": t.alt_m,
            "groundspeed_mps": t.groundspeed_mps,
            "battery_voltage_v": t.battery_voltage_v,
            "battery_remaining_pct": t.battery_remaining_pct,
        }

    def _current_fps(self) -> Optional[float]:
        if len(self._recent_frame_ts) < 2:
            return None
        span = self._recent_frame_ts[-1] - self._recent_frame_ts[0]
        if span <= 0:
            return None
        return (len(self._recent_frame_ts) - 1) / span

    def _build_health_payload(self) -> dict:
        stale = set(self.watchdog.stale_subsystems(REQUIRED_SUBSYSTEMS))
        return {
            "pi_ok": True,
            "camera_ok": "camera" not in stale,
            "ai_ok": "tracker" not in stale,
            "tracker_ok": "tracker" not in stale,
            "mavlink_ok": "mavlink" not in stale,
            "video_ok": self.video_pipeline is not None,
            "recording": self.video_recorder.is_recording if self.video_recorder else False,
            "fps": self._current_fps(),
            # latency_ms/temperature_c need real pipeline timing and Pi
            # thermal-sensor access respectively - out of scope in sim,
            # left as placeholders until M12/hardware bring-up.
            "latency_ms": None,
            "temperature_c": None,
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
    import time

    from sim.mock_fc import MockFlightController
    from sim.synthetic_target import SyntheticTargetGenerator, render_frame
    from companion.comms.video_pipeline import AiortcVideoPipeline
    from companion.vision.camera import SyntheticCamera
    from companion.vision.detector import PassthroughDetector

    hardware_cfg = load_yaml("hardware.yaml")
    network_cfg = load_yaml("network.yaml")
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    safety_cfg = load_yaml("safety_limits.yaml")

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
    orbit_controller = OrbitController(orbit_cfg)
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

    def _sim_frame_source():
        detections = generator.detections_at(time.monotonic())
        return render_frame(
            hardware_cfg["camera"]["width"], hardware_cfg["camera"]["height"], detections
        )

    try:
        video_pipeline = AiortcVideoPipeline(
            frame_source=_sim_frame_source, fps=hardware_cfg["camera"]["target_fps"]
        )
    except RuntimeError:
        log.warning("aiortc not installed - sim mode running without video")
        video_pipeline = None

    orchestrator = CompanionOrchestrator(
        camera=camera, detector=detector, tracker=tracker,
        distance_estimator=distance_estimator, follow_controller=follow_controller,
        orbit_controller=orbit_controller,
        approach_controller=approach_controller, mavlink=mavlink, rc_monitor=rc_monitor,
        supervisor=supervisor, watchdog=watchdog, link=link, recorder=recorder,
        video_pipeline=video_pipeline,
        min_obstacle_distance_m=safety_cfg["min_obstacle_distance_m"],
    )
    return orchestrator, mock_fc


def build_hardware_orchestrator() -> CompanionOrchestrator:
    from companion.comms.video_pipeline import AiortcVideoPipeline
    from companion.vision.camera import Picamera2IMX500Camera
    from companion.vision.detector import IMX500Detector

    hardware_cfg = load_yaml("hardware.yaml")
    network_cfg = load_yaml("network.yaml")
    follow_cfg = load_yaml("follow_limits.yaml")
    orbit_cfg = load_yaml("orbit_limits.yaml")
    approach_cfg = load_yaml("approach_limits.yaml")
    calib_cfg = load_yaml("camera_calibration.yaml")
    safety_cfg = load_yaml("safety_limits.yaml")

    camera = Picamera2IMX500Camera(
        model_path=hardware_cfg["camera"]["imx500_model_path"],
        width=hardware_cfg["camera"]["width"],
        height=hardware_cfg["camera"]["height"],
        target_fps=hardware_cfg["camera"]["target_fps"],
    )
    intrinsics = camera.imx500.network_intrinsics
    detector = IMX500Detector(class_names=intrinsics.labels)
    tracker = IouKalmanTracker()
    distance_estimator = DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg))
    follow_controller = FollowController(follow_cfg)
    orbit_controller = OrbitController(orbit_cfg)
    approach_controller = ApproachTestController(approach_cfg)
    mavlink = MavlinkBridge(
        hardware_cfg["mavlink"]["connection"], baud=hardware_cfg["mavlink"]["baud"]
    )
    rc_monitor = RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"])
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    supervisor = SafetySupervisor(watchdog)
    transport = WebSocketTransport(network_cfg["ws_host"], network_cfg["ws_port"])
    link = GroundStationLink(transport)
    recorder = SessionRecorder(Path.home() / "ai-vision-drone-logs" / "sessions")
    video_recorder = VideoRecorder(
        Path.home() / "ai-vision-drone-logs" / "recordings",
        fps=hardware_cfg["camera"]["target_fps"],
    )

    try:
        video_pipeline = AiortcVideoPipeline(
            frame_source=camera.get_latest_frame, fps=hardware_cfg["camera"]["target_fps"]
        )
    except RuntimeError:
        log.warning("aiortc not installed - hardware mode running without video")
        video_pipeline = None

    return CompanionOrchestrator(
        camera=camera, detector=detector, tracker=tracker,
        distance_estimator=distance_estimator, follow_controller=follow_controller,
        orbit_controller=orbit_controller,
        approach_controller=approach_controller, mavlink=mavlink, rc_monitor=rc_monitor,
        supervisor=supervisor, watchdog=watchdog, link=link, recorder=recorder,
        video_pipeline=video_pipeline, video_recorder=video_recorder,
        min_obstacle_distance_m=safety_cfg["min_obstacle_distance_m"],
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
