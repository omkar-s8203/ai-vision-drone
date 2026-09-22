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
from typing import TYPE_CHECKING, Callable, Optional

from companion.comms.transport import WebSocketTransport
from companion.comms.video_recorder import VideoRecorder
from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachInputs, ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator
from companion.guidance.follow import FollowController
from companion.guidance.geo import bearing_deg, haversine_distance_m
from companion.guidance.grid_search import GridSearchController, GridSearchPhase
from companion.guidance.orbit import OrbitController
from companion.guidance.smart_shot import ShotType, SmartShotController, SmartShotState
from companion.guidance.target_recovery import RecoveryPhase, TargetRecoveryController
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
from companion.tracking.appearance import AppearanceMemory
from companion.tracking.base import Tracker
from companion.tracking.bytetrack_impl import ByteTrackTracker
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
    "dronie": SupervisorState.SMART_SHOT,
    "parabola": SupervisorState.SMART_SHOT,
    "grid_search": SupervisorState.GRID_SEARCH,
}

SHOT_TYPE_MAP = {
    "dronie": ShotType.DRONIE,
    "parabola": ShotType.PARABOLA,
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
        smart_shot_controller: Optional[SmartShotController] = None,
        appearance_memory: Optional[AppearanceMemory] = None,
        recovery_controller: Optional[TargetRecoveryController] = None,
        grid_search_controller: Optional[GridSearchController] = None,
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
        self.smart_shot = smart_shot_controller or SmartShotController(load_yaml("smart_shot_limits.yaml"))
        self.appearance = appearance_memory or AppearanceMemory(**load_yaml("reidentification.yaml"))
        self.recovery = recovery_controller or TargetRecoveryController(load_yaml("target_recovery.yaml"))
        self.grid_search = grid_search_controller or GridSearchController(load_yaml("grid_search_limits.yaml"))
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
        self._was_armed = False  # edge-detects the arm transition to request HOME_POSITION once

        self.link.on_target_selected(self._on_target_selected)
        self.link.on_mode_command(self._on_mode_command)
        self.link.on_abort(self._on_abort)
        self.link.on_arm_command(self._on_arm_command)
        self.link.on_set_flight_mode(self._on_set_flight_mode)
        self.link.on_record_command(self._on_record_command)
        self.link.on_land_confirmation_response(self._on_land_confirmation_response)
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
        mode_str = payload.get("mode", "idle")
        mode = MODE_COMMAND_MAP.get(mode_str, SupervisorState.IDLE)
        # An in-progress target-loss search (companion/guidance/target_recovery.py)
        # is only ever started for Follow/Orbit and otherwise runs to
        # completion on its own timer, deaf to `requested_mode` - previously
        # only _on_abort() cancelled it, so explicitly commanding away from
        # Follow/Orbit (e.g. selecting "Normal RC"/idle) did not stop the
        # yaw-sweep search already in flight. Cancel it here too, for any
        # mode change that isn't itself Follow/Orbit.
        if mode not in (SupervisorState.FOLLOWING, SupervisorState.ORBITING) and self.recovery.is_active:
            self.recovery.cancel()
        # Reset PID integral/derivative state when freshly (re)entering
        # Follow/Orbit, not on every live-parameter update while already
        # active (setFollowSeparation/etc. resend the same mode) - otherwise
        # windup accumulated during a previous stint (or while another mode
        # was active) would bleed into the next one.
        if mode == SupervisorState.FOLLOWING and self.requested_mode != SupervisorState.FOLLOWING:
            self.follow.reset()
        if mode == SupervisorState.ORBITING and self.requested_mode != SupervisorState.ORBITING:
            self.orbit.reset()
        if mode == SupervisorState.GRID_SEARCH and self.requested_mode != SupervisorState.GRID_SEARCH:
            # Freshly entering the mode (not just the app resending the
            # same mode_command, e.g. after some unrelated param change) -
            # plan the sweep from wherever the aircraft actually is right
            # now, per the app's own flow: fly to one corner of the area to
            # search, then engage this mode from there.
            lat = self.mavlink.telemetry.lat
            lon = self.mavlink.telemetry.lon
            width_m = payload.get("grid_search_width_m")
            height_m = payload.get("grid_search_height_m")
            heading_deg = payload.get("grid_search_heading_deg")
            if heading_deg is None:
                heading_deg = self.mavlink.telemetry.heading_deg or 0.0
            if lat is not None and lon is not None and width_m is not None and height_m is not None:
                self.grid_search.start(lat, lon, float(width_m), float(height_m), float(heading_deg))
            else:
                log.error(
                    "Cannot start grid search - missing GPS fix (lat=%s, lon=%s) or area "
                    "dimensions (width_m=%s, height_m=%s)", lat, lon, width_m, height_m,
                )
                mode = SupervisorState.IDLE
        elif mode != SupervisorState.GRID_SEARCH and self.grid_search.phase != GridSearchPhase.IDLE:
            # Deliberately checked against `phase != IDLE`, not `is_active`
            # (True only while SEARCHING) - a deep-audit gap: a sweep that
            # finishes on its own reaches FINISHED, which is already not
            # "active", so a later mode switch never reached this reset at
            # all and the stale finished route (waypoints/current_index)
            # kept streaming to the app's flight map indefinitely, across
            # unrelated later modes, until an explicit abort() (which does
            # call reset()) happened.
            self.grid_search.reset()
        self.requested_mode = mode
        if mode == SupervisorState.APPROACHING:
            self.approach.start()
        else:
            self.approach.stop()
        if mode == SupervisorState.SMART_SHOT:
            shot_type = SHOT_TYPE_MAP.get(mode_str)
            if shot_type is not None and not self.smart_shot.is_active:
                self.smart_shot.start(shot_type)
        else:
            self.smart_shot.stop()
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
        follow_max_speed = payload.get("follow_max_speed_mps")
        if follow_max_speed is not None:
            self.follow.set_max_speed(float(follow_max_speed))
        orbit_max_speed = payload.get("orbit_max_speed_mps")
        if orbit_max_speed is not None:
            self.orbit.set_max_speed(float(orbit_max_speed))
        self.recorder.record(
            "mode_command",
            mode=mode.name,
            follow_separation_m=separation,
            follow_altitude_m=altitude,
            orbit_radius_m=orbit_radius,
            orbit_altitude_m=orbit_altitude,
            follow_max_speed_mps=follow_max_speed,
            orbit_max_speed_mps=orbit_max_speed,
            grid_search_width_m=payload.get("grid_search_width_m"),
            grid_search_height_m=payload.get("grid_search_height_m"),
        )

    def _on_abort(self, payload: dict) -> None:
        self.requested_mode = SupervisorState.IDLE
        self.approach.stop()
        self.smart_shot.stop()
        self.grid_search.reset()
        self.state_machine.stop()
        self.appearance.forget()
        self.recovery.cancel()
        # A real field-reported bug: "the selected target should be
        # forgotten too" on abort. state_machine.stop() above clears the
        # active target, but a TARGET_SELECT that arrived just before the
        # abort (e.g. the operator finishing a drag-select right as they
        # hit Abort) could still be sitting in _pending_selection - left
        # uncleared, the very next process_frame() would see
        # state_machine.state == IDLE (which stop() just set) and silently
        # re-initialize tracking from that stale selection, undoing the
        # abort's own "forget the target" effect one frame later.
        self._pending_selection = None
        self.recorder.record("abort", reason=payload.get("reason"))

        # Setting requested_mode to IDLE above only stops this Pi from
        # sending further guidance velocity setpoints - ArduPilot's own
        # GUIDED-mode setpoint-timeout would eventually hold position on
        # its own once they stop arriving, but that's a passive fallback
        # several seconds slower than commanding it directly, and Abort is
        # a deliberate, explicit operator safety action that deserves an
        # equally immediate, explicit response: actively command BRAKE
        # (ArduCopter's dedicated "stop now and hold this exact position"
        # mode) so the aircraft holds station until the operator picks a
        # new AI mode or flips their own RC switch - never AUTO/a mission,
        # since this project never puts the FC in a scripted mission mode
        # to begin with. Suppressed if the pilot already has RC override -
        # same reasoning as the target-recovery RTL suppression elsewhere
        # in this file: they're already flying manually, so a mode change
        # here would fight their own control instead of helping. Also a
        # no-op with no real MAVLink connection (e.g. unit tests that
        # never call MavlinkBridge.connect()).
        if self.mavlink.is_connected:
            rc_override = self.rc_monitor.is_overriding(self.mavlink.telemetry.rc_channels)
            if not rc_override:
                self.mavlink.set_mode("BRAKE")
                self.recorder.record("abort_hold_commanded")
            else:
                self.recorder.record("abort_hold_suppressed_rc_override")

    def _on_arm_command(self, payload: dict) -> None:
        """Arm/disarm is an administrative FC command, not a guidance
        setpoint - it goes straight to the FC like a standard GCS would send
        it, bypassing the Safety Supervisor's guidance gate (that gate only
        concerns itself with velocity setpoints during active AI guidance).
        `force` (Android's separate "Force disarm" control) is only ever
        meaningful for a disarm - see MavlinkBridge.arm()'s docstring for
        why an unforced disarm can be silently refused by the FC itself."""
        armed = bool(payload.get("armed", False))
        force = bool(payload.get("force", False))
        self.mavlink.arm(armed, force=force)
        self.recorder.record("arm_command", armed=armed, force=force)

    def _on_set_flight_mode(self, payload: dict) -> None:
        mode = str(payload.get("mode", ""))
        ok = self.mavlink.set_mode(mode)
        self.recorder.record("set_flight_mode", mode=mode, accepted=ok)

    def _on_land_confirmation_response(self, payload: dict) -> None:
        """The operator's answer to a land_confirmation_request (target-loss
        recovery timed out with low battery/too far to RTL - see
        companion/guidance/target_recovery.py). Landing is only ever
        triggered here, on an explicit operator decision - never
        automatically, regardless of what the recovery controller or the
        obstacle check concluded."""
        approved = bool(payload.get("approved", False))
        self.recovery.confirm_landing(approved)
        self.recorder.record("land_confirmation_response", approved=approved)
        if approved:
            self.mavlink.set_mode("LAND")
        self.requested_mode = SupervisorState.IDLE

    def _on_record_command(self, payload: dict) -> None:
        asyncio.create_task(self._handle_record_command(bool(payload.get("recording", False))))

    async def _handle_record_command(self, want_recording: bool) -> None:
        if self.video_recorder is None:
            return
        loop = asyncio.get_event_loop()
        if want_recording and not self.video_recorder.is_recording:
            width, height = self._frame_size or (
                self.camera.width if hasattr(self.camera, "width") else 1280,
                self.camera.height if hasattr(self.camera, "height") else 720,
            )
            # Unlike write() (see VideoRecorder's own docstring), start()
            # and stop() are one-off calls, not once-per-frame - offloading
            # them via run_in_executor here is genuinely non-blocking
            # (nothing else is waiting on this coroutine to keep pumping
            # frames), and avoids a real field-reported bug where stop()'s
            # cv2.VideoWriter.release() call froze the live video feed for
            # its whole duration by blocking the shared event loop.
            path = await loop.run_in_executor(None, self.video_recorder.start, width, height)
            if path is not None:
                self.recorder.record("record_start", path=str(path))
            else:
                log.error("VideoRecorder failed to open any codec - recording did not start")
                self.recorder.record("record_start_failed")
        elif not want_recording and self.video_recorder.is_recording:
            path = await loop.run_in_executor(None, self.video_recorder.stop)
            self.recorder.record("record_stop", path=str(path) if path else None)
        await self.link.send_recording_state(
            {
                "recording": self.video_recorder.is_recording,
                "duration_s": self.video_recorder.duration_s,
            }
        )

    def _on_mavlink_message(self, msg: object) -> None:
        self.watchdog.beat("mavlink")
        if msg.get_type() == "RC_CHANNELS":
            # A stale RC_CHANNELS stream would otherwise leave
            # RcOverrideMonitor.is_overriding() stuck returning False
            # forever (docs/safety-case.md) - beating this separately from
            # the broader "mavlink" heartbeat above means the Supervisor
            # (rc_channels is in REQUIRED_SUBSYSTEMS) forces SAFE the
            # moment this specific message stream actually stops, not just
            # when the whole MAVLink link goes down.
            self.watchdog.beat("rc_channels")

    async def start(self) -> None:
        await self.link.start()
        if not self.mavlink.is_connected:
            self.mavlink.connect()
        asyncio.create_task(self.mavlink.run(on_message=self._on_mavlink_message))
        await self._perception_loop()

    def _camera_frame(self):
        """Safe accessor for the camera's latest real pixel array - `camera`
        can be None in tests that drive process_frame() directly without a
        real camera backend, and CameraBase.get_latest_frame() itself
        already returns None for backends with no real image data (sim)."""
        if self.camera is None:
            return None
        return self.camera.get_latest_frame()

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
            frame_bgr = self._camera_frame()
            if frame_bgr is not None:
                # VideoRecorder.write() is non-blocking (submits to its own
                # worker thread and returns immediately) - see its class
                # docstring. It must NOT be awaited via run_in_executor
                # here: that only stops it from blocking other tasks on the
                # event loop, not from stalling this coroutine itself,
                # which is the one actually producing frames for the live
                # feed - awaiting it inline here was the real cause of a
                # field-reported bug ("video gets slow when recording
                # starts").
                self.video_recorder.write(frame_bgr)
        detections = self.detector.parse(frame.raw_detection_output, frame.ts)

        # A real field-reported bug: this used to only fire while
        # state_machine.state == IDLE, so once ANY target had ever been
        # selected, every later TARGET_SELECT (tap-on-video or "Select" in
        # the AI Modes detection list) was silently swallowed - state never
        # returns to IDLE on its own (TRACKING -> REACQUIRE -> TARGET_LOST,
        # then it just stays TARGET_LOST) short of an explicit Abort. An
        # explicit operator re-selection should always take effect
        # immediately regardless of current tracking state - start() fully
        # reinitializes the tracker onto the new detection either way, and
        # is already safe to call from TRACKING/REACQUIRE/TARGET_LOST (see
        # TrackingStateMachine.start()); recovery.update()'s own
        # target_reacquired check (below) cleanly cancels an in-progress
        # search/RTL the same frame if one was running.
        if self._pending_selection is not None:
            if self._pending_selection[0] == "point":
                _, px, py = self._pending_selection
                det = select_target_at_point(detections, px, py)
            else:
                _, bbox = self._pending_selection
                det = select_target(detections, bbox)
            if det is not None:
                self.state_machine.start(frame.ts, det)
                self.appearance.learn(self._camera_frame(), self.state_machine.target)
            self._pending_selection = None

        tracking_state = self.state_machine.update(frame.ts, detections)
        self.watchdog.beat("tracker")

        if tracking_state == TrackingState.TARGET_LOST and self.appearance.has_signature:
            # "AI learning mode": the tracker's own REACQUIRE window (above)
            # is short and motion/IoU-based - this is the longer-term
            # fallback once a target has genuinely left frame and come
            # back, matched by remembered appearance instead of requiring
            # the operator to re-tap it.
            rematch = self.appearance.find_match(self._camera_frame(), detections)
            if rematch is not None:
                self.state_machine.start(frame.ts, rematch)
                self.appearance.learn(self._camera_frame(), self.state_machine.target)
                tracking_state = self.state_machine.state
                self.recorder.record("appearance_reacquired", class_name=rematch.class_name)

        distance_m = None
        det_for_distance = None
        if self.state_machine.target is not None:
            t = self.state_machine.target
            det_for_distance = Detection(
                bbox=t.bbox, score=t.confidence, class_id=t.class_id,
                class_name=t.class_name, frame_ts=frame.ts,
            )
            distance_m, _source = self.distance_estimator.estimate(det_for_distance, trust_rangefinder=True)

        rc_override = self.rc_monitor.is_overriding(self.mavlink.telemetry.rc_channels)
        comms_alive = self.link.is_connected
        if comms_alive:
            self.watchdog.beat("comms")

        obstacle_alert = check_proximity(
            detections, self.distance_estimator, self.min_obstacle_distance_m, tracked_target=det_for_distance
        )
        if obstacle_alert is not None:
            self.recorder.record(
                "obstacle_alert", class_name=obstacle_alert.class_name, distance_m=obstacle_alert.distance_m
            )

        # HOME_POSITION isn't broadcast continuously - request it once right
        # after arming (ArduPilot sets/refreshes home at arm time), so the
        # target-recovery RTL-vs-land distance estimate below has it
        # available without polling every frame.
        armed_now = self.mavlink.telemetry.armed
        if armed_now and not self._was_armed:
            self.mavlink.request_home_position()
        self._was_armed = armed_now

        distance_to_home_m, _home_bearing_deg = self._distance_and_bearing_to_home()

        # Target-loss recovery (docs/safety-case.md): only engages for
        # Follow/Orbit, which is what's actually driving the aircraft
        # toward/around a target - Approach-Test already has its own
        # stricter immediate-abort-on-loss behavior (see supervisor.py) and
        # deliberately doesn't get a search phase.
        if tracking_state == TrackingState.TARGET_LOST and self.requested_mode in (
            SupervisorState.FOLLOWING,
            SupervisorState.ORBITING,
        ):
            self.recovery.start_search(frame.ts)

        recovery_result = self.recovery.update(
            now=frame.ts,
            target_reacquired=tracking_state == TrackingState.TRACKING,
            distance_to_home_m=distance_to_home_m,
            battery_remaining_pct=self.mavlink.telemetry.battery_remaining_pct,
            obstacle_detected=obstacle_alert is not None,
            obstacle_class_name=obstacle_alert.class_name if obstacle_alert else None,
        )

        effective_requested_state = self.requested_mode
        if recovery_result.phase == RecoveryPhase.SEARCHING:
            effective_requested_state = SupervisorState.SEARCHING
        elif recovery_result.phase == RecoveryPhase.FOUND:
            self.recorder.record("target_recovery_found")
        elif recovery_result.phase == RecoveryPhase.RTL_TRIGGERED:
            # RTL is a direct FC mode change (like arm()/set_mode()), deliberately
            # not gated through SafetySupervisor.evaluate() - but that means it
            # was previously fired unconditionally even if the pilot had already
            # taken RC stick override mid-search, contradicting "RC override
            # always takes precedence" (docs/safety-case.md). Suppress it in
            # that case: the pilot is already flying manually, so there is
            # nothing for an autonomous RTL to usefully override.
            if not rc_override:
                self.mavlink.set_mode("RTL")
                self.recorder.record(
                    "target_recovery_rtl", distance_to_home_m=recovery_result.distance_to_home_m
                )
            else:
                self.recorder.record(
                    "target_recovery_rtl_suppressed_rc_override",
                    distance_to_home_m=recovery_result.distance_to_home_m,
                )
            self.requested_mode = SupervisorState.IDLE
            effective_requested_state = SupervisorState.IDLE
        elif recovery_result.phase == RecoveryPhase.LAND_CONFIRMATION_REQUESTED:
            effective_requested_state = SupervisorState.IDLE  # hold - no guidance command while waiting
            await self.link.send_land_confirmation_request(
                {
                    "distance_to_home_m": recovery_result.distance_to_home_m,
                    "battery_remaining_pct": self.mavlink.telemetry.battery_remaining_pct,
                    "obstacle_detected": recovery_result.obstacle_detected,
                    "obstacle_class_name": recovery_result.obstacle_class_name,
                }
            )
            self.recorder.record(
                "target_recovery_land_confirmation_requested",
                distance_to_home_m=recovery_result.distance_to_home_m,
                obstacle_detected=recovery_result.obstacle_detected,
            )
        elif recovery_result.phase == RecoveryPhase.AWAITING_LAND_CONFIRMATION:
            effective_requested_state = SupervisorState.IDLE  # still holding - request already sent, don't resend

        decision = self.supervisor.evaluate(
            SupervisorInputs(
                fc_mode=self.mavlink.telemetry.fc_mode,
                ai_guidance_mode_name=AI_GUIDANCE_MODE_NAME,
                rc_override_active=rc_override,
                tracking_state=tracking_state,
                comms_alive=comms_alive,
                requested_state=effective_requested_state,
                obstacle_alert=obstacle_alert,
            )
        )

        dt = 0.0 if self._last_frame_ts is None else max(0.0, frame.ts - self._last_frame_ts)
        self._last_frame_ts = frame.ts

        command = None
        if decision.state == SupervisorState.SEARCHING:
            command = recovery_result.command
        elif decision.state == SupervisorState.FOLLOWING and self.state_machine.target is not None:
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
                    geofence_breached=self.mavlink.telemetry.fence_breached,
                )
            )
            command = result.command
            if result.abort_reason:
                self.recorder.record("approach_abort", reason=result.abort_reason)
        elif decision.state == SupervisorState.SMART_SHOT:
            shot_result = self.smart_shot.update(
                self.state_machine.target, frame.width, frame.height, dt
            )
            command = shot_result.command
            if shot_result.state == SmartShotState.FINISHED:
                # Unlike Approach-Test's STOPPED_AT_BOUNDARY (a safety-
                # relevant state deliberately left "stuck" until the
                # operator explicitly decides what's next), a finished
                # smart shot has no residual safety significance - drop
                # straight back to IDLE so `supervisor_state` (sent to the
                # app every frame) correctly reflects that guidance is over,
                # instead of reporting SMART_SHOT forever with no command
                # actually being sent.
                self.requested_mode = SupervisorState.IDLE
                self.recorder.record("smart_shot_finished")
        elif decision.state == SupervisorState.GRID_SEARCH:
            command = self.grid_search.compute(
                self.mavlink.telemetry.lat,
                self.mavlink.telemetry.lon,
                self.mavlink.telemetry.heading_deg,
                self.mavlink.telemetry.alt_m,
                dt,
            )
            if self.grid_search.phase == GridSearchPhase.FINISHED:
                # Same reasoning as a finished smart shot above: no residual
                # safety significance once every waypoint is visited, so
                # drop straight back to IDLE rather than reporting
                # GRID_SEARCH forever with no command actually being sent.
                self.requested_mode = SupervisorState.IDLE
                self.recorder.record("grid_search_finished")

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
                # Previously only written to the session log file, reviewable
                # only after the fact - the plan's own bench-test procedure
                # (props off, watch commanded velocities before ever arming)
                # needs this live on the operator's screen, not just in a
                # log an operator isn't SSH'd in to read during the test.
                "commanded_vx_mps": command.vx_mps if command is not None else None,
                "commanded_vy_mps": command.vy_mps if command is not None else None,
                "commanded_vz_mps": command.vz_mps if command is not None else None,
                "commanded_yaw_rate_rads": command.yaw_rate_rads if command is not None else None,
                "guidance_sent": sent,
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
        grid_search_status = self.grid_search.status()
        await self.link.send_grid_search_update(
            {
                "active": self.grid_search.is_active,
                "phase": grid_search_status.phase.name,
                "waypoints": [[lat, lon] for lat, lon in grid_search_status.waypoints],
                "current_index": grid_search_status.current_index,
            }
        )
        await self.link.send_telemetry(self._build_telemetry_payload())
        await self.link.send_health(self._build_health_payload())
        if self.video_recorder is not None and self.video_recorder.is_recording:
            # _handle_record_command only sends recording_state once, right
            # when the operator toggles it - with duration_s pinned at
            # whatever it was at that instant. Without this, the Android
            # RecordButton's timer is frozen at 0:00 for the entire
            # recording even though it's genuinely running on the Pi (a
            # real bug reported from the field: "I don't know if it's
            # actually recording"). Piggyback the running duration on the
            # per-frame broadcast like telemetry/health already do.
            await self.link.send_recording_state(
                {
                    "recording": True,
                    "duration_s": self.video_recorder.duration_s,
                }
            )

        return {
            "tracking_state": tracking_state,
            "supervisor_decision": decision,
            "command_sent": sent,
        }

    def _distance_and_bearing_to_home(self) -> tuple[Optional[float], Optional[float]]:
        """Real geodesy off HOME_POSITION + the current GPS fix - both None
        until home is known (see request_home_position()) and a fix exists.
        Shared by the target-recovery RTL-vs-land estimate and the Status
        tab's telemetry payload/home-radar widget so there's one source of
        truth instead of two computations that could drift apart."""
        t = self.mavlink.telemetry
        if None in (t.home_lat, t.home_lon, t.lat, t.lon):
            return None, None
        distance_m = haversine_distance_m(t.home_lat, t.home_lon, t.lat, t.lon)
        bearing = bearing_deg(t.lat, t.lon, t.home_lat, t.home_lon)
        return distance_m, bearing

    def _build_telemetry_payload(self) -> dict:
        t = self.mavlink.telemetry
        distance_to_home_m, home_bearing_deg = self._distance_and_bearing_to_home()
        return {
            "fc_mode": t.fc_mode,
            "armed": t.armed,
            "lat": t.lat,
            "lon": t.lon,
            "alt_m": t.alt_m,
            "groundspeed_mps": t.groundspeed_mps,
            "battery_voltage_v": t.battery_voltage_v,
            "battery_remaining_pct": t.battery_remaining_pct,
            "current_battery_a": t.current_battery_a,
            "fence_enabled": t.fence_enabled,
            "fence_breached": t.fence_breached,
            "satellites_visible": t.satellites_visible,
            "gps_fix_type": t.gps_fix_type,
            "hdop": t.hdop,
            "vdop": t.vdop,
            "home_lat": t.home_lat,
            "home_lon": t.home_lon,
            "distance_to_home_m": distance_to_home_m,
            "home_bearing_deg": home_bearing_deg,
            "roll_deg": t.roll_deg,
            "pitch_deg": t.pitch_deg,
            "yaw_deg": t.yaw_deg,
            "heading_deg": t.heading_deg,
            "airspeed_mps": t.airspeed_mps,
            "climb_mps": t.climb_mps,
            "throttle_pct": t.throttle_pct,
            "rc_rssi_pct": t.rc_rssi_pct,
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
        # A real robustness gap found in a code-review audit: process_frame()
        # ran here with no exception handling at all - a bug anywhere in
        # it (a config typo, an unexpected None, a new guidance controller
        # like grid_search.py hitting a case its own unit tests didn't
        # cover) would propagate straight out of this loop and out of
        # start() itself, killing camera capture, video, MAVLink, and
        # telemetry all at once over what might only be one bad frame.
        # systemd's Restart=on-failure would eventually recover it, but a
        # full process restart is a far more disruptive failure mode than
        # skipping one frame and continuing - guidance for that one frame
        # is simply not sent (the same safe "no command" outcome as any
        # other frame where a controller returns nothing), not a crash.
        async for frame in self.camera.frames():
            try:
                await self.process_frame(frame)
            except Exception:
                log.exception("process_frame() raised - skipping this frame, camera loop stays alive")


SIM_FC_UDP_PORT = 14550
SIM_BRIDGE_UDP_PORT = 14551


def build_tracker(hardware_cfg: dict) -> Tracker:
    """Picks the tracker implementation from `hardware.yaml`'s `tracker.impl`
    (default "iou", also accepts "bytetrack") instead of hardcoding
    IouKalmanTracker - ByteTrackTracker is fully implemented and unit-tested
    (companion/tracking/bytetrack_impl.py) but has never been run against
    real hardware, so it stays opt-in via config rather than the default."""
    tracker_cfg = hardware_cfg.get("tracker", {})
    impl = tracker_cfg.get("impl", "iou")
    if impl == "bytetrack":
        return ByteTrackTracker(
            high_score_thresh=tracker_cfg.get("high_score_thresh", 0.6),
            low_score_thresh=tracker_cfg.get("low_score_thresh", 0.1),
            min_iou=tracker_cfg.get("min_iou", 0.3),
        )
    if impl != "iou":
        raise ValueError(f"Unknown tracker.impl {impl!r} in hardware.yaml - expected 'iou' or 'bytetrack'")
    return IouKalmanTracker()


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
    smart_shot_cfg = load_yaml("smart_shot_limits.yaml")

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
    tracker = build_tracker(hardware_cfg)
    distance_estimator = DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg))
    follow_controller = FollowController(follow_cfg)
    orbit_controller = OrbitController(orbit_cfg)
    approach_controller = ApproachTestController(approach_cfg)
    smart_shot_controller = SmartShotController(smart_shot_cfg)

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
        smart_shot_controller=smart_shot_controller,
        min_obstacle_distance_m=safety_cfg["min_obstacle_distance_m"],
    )
    return orchestrator, mock_fc


def wrap_frame_source_with_latency_overlay(frame_source: Callable) -> Callable:
    """Wraps a frame_source callable so every frame gets a burned-in
    wall-clock timestamp (docs plan M5's own suggested glass-to-glass
    latency test method) - opt-in via the AI_VISION_DRONE_LATENCY_OVERLAY=1
    env var, never on by default, since it visibly stamps every frame."""
    from companion.comms.video_pipeline import overlay_latency_timestamp

    def wrapped():
        frame = frame_source()
        return None if frame is None else overlay_latency_timestamp(frame)

    return wrapped


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
    smart_shot_cfg = load_yaml("smart_shot_limits.yaml")

    camera = Picamera2IMX500Camera(
        model_path=hardware_cfg["camera"]["imx500_model_path"],
        width=hardware_cfg["camera"]["width"],
        height=hardware_cfg["camera"]["height"],
        target_fps=hardware_cfg["camera"]["target_fps"],
    )
    intrinsics = camera.imx500.network_intrinsics
    detector = IMX500Detector(
        class_names=intrinsics.labels,
        score_threshold=hardware_cfg["camera"].get("score_threshold", 0.5),
    )
    tracker = build_tracker(hardware_cfg)
    rangefinder = None
    rangefinder_cfg = hardware_cfg.get("rangefinder", {})
    if rangefinder_cfg.get("enabled"):
        from companion.guidance.rangefinder import TFMiniRangefinderSource

        rangefinder = TFMiniRangefinderSource.open(
            rangefinder_cfg["port"], baud=rangefinder_cfg.get("baud", 115200)
        )
    distance_estimator = DistanceEstimator(CameraIntrinsics.from_dict(calib_cfg), rangefinder=rangefinder)
    follow_controller = FollowController(follow_cfg)
    orbit_controller = OrbitController(orbit_cfg)
    approach_controller = ApproachTestController(approach_cfg)
    smart_shot_controller = SmartShotController(smart_shot_cfg)
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

    frame_source = camera.get_latest_frame
    if os.environ.get("AI_VISION_DRONE_LATENCY_OVERLAY") == "1":
        frame_source = wrap_frame_source_with_latency_overlay(frame_source)
        log.warning("AI_VISION_DRONE_LATENCY_OVERLAY=1: every video frame is stamped with a wall-clock timestamp (M5 latency test)")

    try:
        video_pipeline = AiortcVideoPipeline(
            frame_source=frame_source, fps=hardware_cfg["camera"]["target_fps"]
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
        smart_shot_controller=smart_shot_controller,
        min_obstacle_distance_m=safety_cfg["min_obstacle_distance_m"],
    )


class StartupHealthCheckError(Exception):
    """Raised by run_startup_health_check() when config the orchestrator
    will unconditionally index into is missing or unparseable. Deliberately
    a distinct exception type (not a bare KeyError/ValueError) so _amain()
    can log it as a clearly-labeled startup failure instead of a raw
    traceback with no indication of which config file or field was wrong."""


def run_startup_health_check(mode: str) -> None:
    """Boot-time health self-check (docs plan M15) - confirms every config
    file build_sim_orchestrator()/build_hardware_orchestrator() will read
    actually parses and has the keys they unconditionally index into,
    *before* either function ever touches real hardware (camera, MAVLink).
    Without this, a missing/misspelled YAML key surfaces as a bare
    KeyError several stack frames into camera/MAVLink construction, which
    on a real Pi bench session means digging through a traceback instead of
    reading one clear line in the journal. Raises StartupHealthCheckError
    listing every problem found at once (not just the first); does nothing
    if everything required is present.

    Deliberately conservative: only checks that config is well-formed, not
    that the camera/MAVLink hardware itself is healthy - build_hardware_
    orchestrator() and orchestrator.start() still do that real work (and
    can still fail for real hardware reasons this can't predict), this
    just rules out the config-typo class of failure first, cheaply and
    with no side effects.
    """
    problems: list[str] = []

    def _require(cfg: dict, path: list[str], file_name: str) -> None:
        node = cfg
        for key in path:
            if not isinstance(node, dict) or key not in node:
                problems.append(f"{file_name}: missing required key {'.'.join(path)!r}")
                return
            node = node[key]

    def _load(file_name: str) -> dict:
        try:
            return load_yaml(file_name)
        except Exception as exc:
            problems.append(f"{file_name}: failed to parse ({exc})")
            return {}

    hardware_cfg = _load("hardware.yaml")
    for path in (["camera", "width"], ["camera", "height"], ["camera", "target_fps"]):
        _require(hardware_cfg, path, "hardware.yaml")
    if mode != "sim":
        _require(hardware_cfg, ["camera", "imx500_model_path"], "hardware.yaml")
        _require(hardware_cfg, ["mavlink", "connection"], "hardware.yaml")
        _require(hardware_cfg, ["mavlink", "baud"], "hardware.yaml")

    network_cfg = _load("network.yaml")
    _require(network_cfg, ["ws_host"], "network.yaml")
    _require(network_cfg, ["ws_port"], "network.yaml")

    approach_cfg = _load("approach_limits.yaml")
    _require(approach_cfg, ["rc_override_deadband"], "approach_limits.yaml")

    safety_cfg = _load("safety_limits.yaml")
    _require(safety_cfg, ["min_obstacle_distance_m"], "safety_limits.yaml")

    # A deep-audit gap: this file used to only be parse-checked below like
    # the others, but GridSearchController's __init__ unconditionally
    # indexes pid.yaw/pid.altitude/max_yaw_rate_rads/max_speed_mps (so a
    # missing key here fails at orchestrator construction, right after this
    # check would have falsely reported "passed"), and its start()/compute()
    # unconditionally index the rest - only ever hit once grid search is
    # actually engaged, possibly mid-flight, which is an even worse time to
    # discover a config typo.
    grid_search_cfg = _load("grid_search_limits.yaml")
    for path in (
        ["pid", "yaw"],
        ["pid", "altitude"],
        ["max_yaw_rate_rads"],
        ["max_speed_mps"],
        ["leg_spacing_m"],
        ["waypoint_radius_m"],
        ["max_heading_error_deg_to_advance"],
        ["search_speed_mps"],
    ):
        _require(grid_search_cfg, path, "grid_search_limits.yaml")

    # These are read in full (unpacked as **kwargs, or indexed piecemeal by
    # their own controllers) but have no single required top-level key this
    # check can name usefully - just confirm each one actually parses.
    for file_name in (
        "follow_limits.yaml",
        "orbit_limits.yaml",
        "camera_calibration.yaml",
        "smart_shot_limits.yaml",
        "reidentification.yaml",
        "target_recovery.yaml",
    ):
        _load(file_name)

    if problems:
        raise StartupHealthCheckError(
            f"Startup health check failed - refusing to start ({len(problems)} problem(s)):\n"
            + "\n".join(f"  - {p}" for p in problems)
        )


async def _amain() -> None:
    mode = os.environ.get("COMPANION_MODE", "sim")
    configure_logging(Path("companion/logs"))
    log.info("Starting companion orchestrator in %s mode", mode)

    try:
        run_startup_health_check(mode)
    except StartupHealthCheckError as exc:
        log.error(str(exc))
        raise SystemExit(1) from exc
    log.info("Startup health check passed (config is well-formed) - initializing hardware/orchestrator")

    background_tasks: list[asyncio.Task] = []
    try:
        if mode == "sim":
            orchestrator, mock_fc = build_sim_orchestrator()
            background_tasks.append(asyncio.create_task(mock_fc.run(rate_hz=10.0)))
        else:
            orchestrator = build_hardware_orchestrator()
    except Exception:
        log.exception("Startup failed while initializing hardware/orchestrator - see the real cause above")
        raise

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
