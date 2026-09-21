package com.aivisiondrone.groundstation

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aivisiondrone.groundstation.audio.AlertEvent
import com.aivisiondrone.groundstation.comms.Envelope
import com.aivisiondrone.groundstation.comms.GroundStationClient
import com.aivisiondrone.groundstation.comms.MessageType
import com.aivisiondrone.groundstation.comms.optDoubleOrNull
import com.aivisiondrone.groundstation.comms.optIntOrNull
import com.aivisiondrone.groundstation.comms.optStringOrNull
import com.aivisiondrone.groundstation.control.DetectionHeatmap
import com.aivisiondrone.groundstation.control.DroneMode
import com.aivisiondrone.groundstation.control.HeatmapSnapshot
import com.aivisiondrone.groundstation.control.TargetTrail
import com.aivisiondrone.groundstation.control.TrailSnapshot
import com.aivisiondrone.groundstation.telemetry.DetectionsState
import com.aivisiondrone.groundstation.telemetry.HealthState
import com.aivisiondrone.groundstation.telemetry.LandConfirmationRequest
import com.aivisiondrone.groundstation.telemetry.RawDetection
import com.aivisiondrone.groundstation.telemetry.RecordingState
import com.aivisiondrone.groundstation.telemetry.TargetBBox
import com.aivisiondrone.groundstation.telemetry.TelemetryState
import com.aivisiondrone.groundstation.telemetry.TrackingState
import com.aivisiondrone.groundstation.video.LocalRecordingOutput
import com.aivisiondrone.groundstation.video.LocalVideoRecorder
import com.aivisiondrone.groundstation.video.WebRtcClient
import com.aivisiondrone.groundstation.comms.LinkState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.webrtc.EglBase
import org.webrtc.VideoTrack

private const val RECONNECT_DELAY_MS = 3000L

// Mirrors the relevant subset of companion/safety/supervisor.py's
// SupervisorState names - see the TRACKING_UPDATE handling below.
private val SAFE_OR_IDLE_STATES = setOf("IDLE", "SAFE")
private val ONE_SHOT_MODES = setOf(DroneMode.DRONIE, DroneMode.PARABOLA)

// Supervisor states that were actively driving the aircraft - used to tell
// a real forced-SAFE (guidance was running, now isn't) from just idling.
private val ACTIVE_GUIDANCE_STATES = setOf("FOLLOWING", "ORBITING", "APPROACHING", "SEARCHING", "SMART_SHOT")

/**
 * Ties the WebSocket control/telemetry channel and the WebRTC video channel
 * together into the state the Compose UI renders (docs plan M6). Video and
 * comms stay on separate underlying transports so a video hiccup never
 * blocks an abort command.
 */
class MainViewModel : ViewModel() {
    private val client = GroundStationClient()
    private var webRtcClient: WebRtcClient? = null
    private var appContext: Context? = null
    private var eglBase: EglBase? = null
    private var localVideoRecorder: LocalVideoRecorder? = null

    val linkState = client.linkState

    private val _telemetry = MutableStateFlow(TelemetryState())
    val telemetry = _telemetry.asStateFlow()

    private val _health = MutableStateFlow(HealthState())
    val health = _health.asStateFlow()

    private val _tracking = MutableStateFlow(TrackingState())
    val tracking = _tracking.asStateFlow()

    private val _detections = MutableStateFlow(DetectionsState())
    val detections = _detections.asStateFlow()

    /** "Where has the AI been seeing things" overlay, built from the same
     * detections_update stream as `detections` above - see
     * control/DetectionHeatmap.kt. Opt-in via `showHeatmap`, off by
     * default so it doesn't clutter the live view unasked. */
    private val detectionHeatmap = DetectionHeatmap()
    private val _heatmapSnapshot = MutableStateFlow(HeatmapSnapshot.EMPTY)
    val heatmapSnapshot = _heatmapSnapshot.asStateFlow()

    private val _showHeatmap = MutableStateFlow(false)
    val showHeatmap = _showHeatmap.asStateFlow()

    fun setShowHeatmap(show: Boolean) {
        _showHeatmap.value = show
    }

    /** The currently-tracked target's recent movement path - see
     * control/TargetTrail.kt. A field request: "add visual patterns /
     * spatial patterns feature," clarified as a target movement trail.
     * Shown whenever a target is actively tracked (not a separate toggle
     * like the heatmap - it's directly tied to what's already on screen,
     * the tracked target's own box, rather than a general-purpose overlay
     * that could clutter an otherwise-empty view). */
    private val targetTrail = TargetTrail()
    private val _trailSnapshot = MutableStateFlow(TrailSnapshot(emptyList(), null, null))
    val trailSnapshot = _trailSnapshot.asStateFlow()

    /** Perimeter/intrusion zone - a defence-relevant field request:
     * "perimeter / intrusion alert." The operator drags out a rectangle on
     * the live video (FlyTab's "PERIMETER" HUD chip); any live detection
     * whose center falls inside it fires PERIMETER_BREACHED (and
     * PERIMETER_CLEARED once nothing remains inside) - see
     * checkPerimeterIntrusion() below. In the Pi's own reported video
     * coordinate space, the same as tracking/detections bboxes, not screen
     * pixels - PerimeterZoneOverlay rescales the same way TrackingOverlay
     * already does. */
    private val _perimeterZone = MutableStateFlow<TargetBBox?>(null)
    val perimeterZone = _perimeterZone.asStateFlow()

    private val _perimeterBreached = MutableStateFlow(false)
    val perimeterBreached = _perimeterBreached.asStateFlow()

    fun setPerimeterZone(zone: TargetBBox) {
        _perimeterZone.value = zone
        _perimeterBreached.value = false
    }

    fun clearPerimeterZone() {
        _perimeterZone.value = null
        _perimeterBreached.value = false
    }

    /** Edge-triggered on "any detection inside the zone" as a whole, not
     * per-object identity - unlike the one actively tracked target,
     * general detections in `detections_update` have no persistent ID to
     * follow individually frame to frame, so this fires once when the zone
     * goes from empty to occupied (and once when it empties again) rather
     * than trying to count distinct intrusions. */
    private fun checkPerimeterIntrusion(detections: DetectionsState) {
        val zone = _perimeterZone.value ?: return
        val occupiedNow = detections.detections.any { detection ->
            val cx = detection.bbox.x + detection.bbox.w / 2.0
            val cy = detection.bbox.y + detection.bbox.h / 2.0
            cx >= zone.x && cx <= zone.x + zone.w && cy >= zone.y && cy <= zone.y + zone.h
        }
        if (occupiedNow && !_perimeterBreached.value) {
            _alertEvents.tryEmit(AlertEvent.PERIMETER_BREACHED)
        } else if (!occupiedNow && _perimeterBreached.value) {
            _alertEvents.tryEmit(AlertEvent.PERIMETER_CLEARED)
        }
        _perimeterBreached.value = occupiedNow
    }

    /** Non-null exactly while a land_confirmation_request is awaiting the
     * operator's answer - see LandConfirmationDialog.kt. */
    private val _landConfirmationRequest = MutableStateFlow<LandConfirmationRequest?>(null)
    val landConfirmationRequest = _landConfirmationRequest.asStateFlow()

    private val _mode = MutableStateFlow(DroneMode.IDLE)
    val mode = _mode.asStateFlow()

    private val _followSeparationM = MutableStateFlow(6f)
    val followSeparationM = _followSeparationM.asStateFlow()

    private val _followAltitudeM = MutableStateFlow(10f)
    val followAltitudeM = _followAltitudeM.asStateFlow()

    private val _orbitRadiusM = MutableStateFlow(8f)
    val orbitRadiusM = _orbitRadiusM.asStateFlow()

    private val _orbitAltitudeM = MutableStateFlow(10f)
    val orbitAltitudeM = _orbitAltitudeM.asStateFlow()

    // Defaults match follow_limits.yaml/orbit_limits.yaml's max_speed_mps
    // ceiling - the slider starts at "full speed" and only ever dials
    // down from there (see FollowController/OrbitController.set_max_speed).
    private val _followMaxSpeedMps = MutableStateFlow(3f)
    val followMaxSpeedMps = _followMaxSpeedMps.asStateFlow()

    private val _orbitMaxSpeedMps = MutableStateFlow(3f)
    val orbitMaxSpeedMps = _orbitMaxSpeedMps.asStateFlow()

    private val _recording = MutableStateFlow(RecordingState())
    val recording = _recording.asStateFlow()

    /** True right after a tap-select, until the operator picks Track/
     * Follow/Orbit (or cancels) from the DJI-style quick action sheet. */
    private val _showTargetActionSheet = MutableStateFlow(false)
    val showTargetActionSheet = _showTargetActionSheet.asStateFlow()

    private val _remoteVideoTrack = MutableStateFlow<VideoTrack?>(null)
    val remoteVideoTrack = _remoteVideoTrack.asStateFlow()

    /** Edge-triggered tracking/guidance state-change events for the buzzer/
     * voice alert system (see audio/AlertSoundPlayer.kt) - each fires once
     * per real transition, not once per telemetry frame. Buffered (not
     * conflated) so two alerts arriving in the same frame (e.g. target
     * lost + search started) both reach the collector. */
    private val _alertEvents = MutableSharedFlow<AlertEvent>(extraBufferCapacity = 8)
    val alertEvents = _alertEvents.asSharedFlow()

    /** Tells the alert player (owned at the Compose layer, not here - see
     * GroundStationScreen) to immediately silence itself, clearing any
     * queued/in-progress speech - a real field-reported bug: hitting Abort
     * used to leave a backlog of already-queued TTS lines (e.g. "Target
     * lost" -> "Searching" -> "Returning home", queued up in the seconds
     * before the operator reacted) still talking for several seconds after
     * the abort itself had already taken effect. */
    private val _stopAlerts = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val stopAlerts = _stopAlerts.asSharedFlow()

    private val _alertsMuted = MutableStateFlow(false)
    val alertsMuted = _alertsMuted.asStateFlow()

    private val _isDarkMode = MutableStateFlow(true)
    val isDarkMode = _isDarkMode.asStateFlow()

    fun setDarkMode(dark: Boolean) {
        _isDarkMode.value = dark
    }

    fun setAlertsMuted(muted: Boolean) {
        _alertsMuted.value = muted
    }

    init {
        viewModelScope.launch {
            client.messages.collect { envelope -> handleEnvelope(envelope) }
        }
        viewModelScope.launch {
            client.linkState.collect { state ->
                when (state) {
                    // Every CONNECTED transition re-establishes video, not
                    // just the very first one - this is also what makes
                    // the very first connect's video negotiation happen,
                    // see reestablishVideo()'s own docstring for the real
                    // field-reported bug this fixes.
                    LinkState.CONNECTED -> reestablishVideo()
                    LinkState.DISCONNECTED -> {
                        if (client.shouldAutoReconnect) {
                            delay(RECONNECT_DELAY_MS)
                            if (client.shouldAutoReconnect) {
                                client.reconnect()
                            }
                        }
                    }
                    LinkState.CONNECTING -> {}
                }
            }
        }
    }

    fun connect(context: Context, eglBase: EglBase, host: String, port: Int) {
        appContext = context.applicationContext
        this.eglBase = eglBase
        client.connect(host, port)
    }

    /** (Re)builds the WebRTC video session from scratch. Called every time
     * the control link becomes CONNECTED - including after an automatic
     * WS reconnect (e.g. the Pi service restarting, or a brief WiFi drop),
     * not just the operator's initial "Connect" tap.
     *
     * **Fixes a real field-reported bug**: "the app shows connected but the
     * camera is a black screen; restarting the app fixes it." The WS
     * control channel and WebRTC video are deliberately separate
     * transports (docs plan M5/M6) so a video hiccup never blocks an
     * abort command - but that separation meant a WS reconnect never told
     * WebRTC anything happened. `connect()` used to build `webRtcClient`
     * once, guarded by `if (webRtcClient == null)`, so after the *first*
     * connection succeeded, every later reconnect left that same, by-then
     * stale `RTCPeerConnection` in place - its underlying connection had
     * already died along with whatever caused the drop, but nothing ever
     * closed it or sent a fresh offer, so no new video track (or frames)
     * could ever arrive. Restarting the app was the only thing that
     * happened to work, because it threw away the ViewModel (and the dead
     * PeerConnection with it) and built everything from scratch. Now every
     * CONNECTED transition tears down any existing client and starts a
     * completely fresh negotiation, the exact same way a first connect
     * already did - `AiortcVideoPipeline.handle_offer()` on the Pi side
     * already creates a brand new `RTCPeerConnection` per offer it
     * receives, so it was always ready for this, nothing needed to change
     * there.
     */
    private fun reestablishVideo() {
        val context = appContext ?: return
        val eglBase = this.eglBase ?: return
        webRtcClient?.close()
        _remoteVideoTrack.value = null
        webRtcClient = WebRtcClient(
            context = context,
            eglBase = eglBase,
            onLocalOffer = { sdp, type -> client.sendWebRtcOffer(sdp, type) },
            onRemoteVideoTrack = { track -> _remoteVideoTrack.value = track },
        ).also { it.startReceiving() }
    }

    fun disconnect() {
        stopLocalRecording()
        client.disconnect()
        webRtcClient?.close()
        webRtcClient = null
        _remoteVideoTrack.value = null
    }

    fun selectTarget(x: Double, y: Double, w: Double, h: Double) {
        client.sendTargetSelect(x, y, w, h)
        setMode(DroneMode.TRACKING)
        _showTargetActionSheet.value = true
    }

    /** Tap-to-select on one of the live detection boxes, instead of
     * dragging out a new selection rectangle. Immediately locks tracking
     * (like DJI's focus-track box snapping to the subject) and opens the
     * quick action sheet so the operator picks what the drone should then
     * do about it (Track only / Follow / Orbit). */
    fun selectTargetAtPoint(x: Double, y: Double) {
        client.sendTargetSelectAtPoint(x, y)
        setMode(DroneMode.TRACKING)
        _showTargetActionSheet.value = true
    }

    fun dismissTargetActionSheet() {
        _showTargetActionSheet.value = false
    }

    /** Cancels the pending target lock entirely - equivalent to tapping
     * Cancel on DJI's focus-track prompt. */
    fun cancelTargetSelection() {
        _showTargetActionSheet.value = false
        abort()
    }

    fun setMode(newMode: DroneMode) {
        _mode.value = newMode
        val separation = if (newMode == DroneMode.FOLLOWING) _followSeparationM.value.toDouble() else null
        val followAltitude = if (newMode == DroneMode.FOLLOWING) _followAltitudeM.value.toDouble() else null
        val orbitRadius = if (newMode == DroneMode.ORBITING) _orbitRadiusM.value.toDouble() else null
        val orbitAltitude = if (newMode == DroneMode.ORBITING) _orbitAltitudeM.value.toDouble() else null
        val followMaxSpeed = if (newMode == DroneMode.FOLLOWING) _followMaxSpeedMps.value.toDouble() else null
        val orbitMaxSpeed = if (newMode == DroneMode.ORBITING) _orbitMaxSpeedMps.value.toDouble() else null
        client.sendModeCommand(
            newMode.wireValue, separation, followAltitude, orbitRadius, orbitAltitude,
            followMaxSpeed, orbitMaxSpeed,
        )
    }

    /** Chooses an action from the quick action sheet after a tap-select -
     * thin wrapper over setMode() that also closes the sheet. */
    fun chooseTargetAction(newMode: DroneMode) {
        _showTargetActionSheet.value = false
        setMode(newMode)
    }

    fun setFollowSeparation(meters: Float) {
        _followSeparationM.value = meters
        // Live-update the Pi's FollowController while Follow is already
        // active, not just at the moment the mode is first selected.
        if (_mode.value == DroneMode.FOLLOWING) {
            client.sendModeCommand(DroneMode.FOLLOWING.wireValue, meters.toDouble(), _followAltitudeM.value.toDouble())
        }
    }

    fun setFollowAltitude(meters: Float) {
        _followAltitudeM.value = meters
        if (_mode.value == DroneMode.FOLLOWING) {
            client.sendModeCommand(DroneMode.FOLLOWING.wireValue, _followSeparationM.value.toDouble(), meters.toDouble())
        }
    }

    fun setOrbitRadius(meters: Float) {
        _orbitRadiusM.value = meters
        if (_mode.value == DroneMode.ORBITING) {
            client.sendModeCommand(
                DroneMode.ORBITING.wireValue, orbitRadiusM = meters.toDouble(),
                orbitAltitudeM = _orbitAltitudeM.value.toDouble(),
            )
        }
    }

    fun setOrbitAltitude(meters: Float) {
        _orbitAltitudeM.value = meters
        if (_mode.value == DroneMode.ORBITING) {
            client.sendModeCommand(
                DroneMode.ORBITING.wireValue, orbitRadiusM = _orbitRadiusM.value.toDouble(),
                orbitAltitudeM = meters.toDouble(),
            )
        }
    }

    /** The speed slider - clamped server-side to [min_speed_mps, the
     * configured max_speed_mps ceiling] (FollowController.set_max_speed),
     * so this can only ever make the drone slower than its safety-vetted
     * config ceiling, never faster. */
    fun setFollowMaxSpeed(metersPerSecond: Float) {
        _followMaxSpeedMps.value = metersPerSecond
        if (_mode.value == DroneMode.FOLLOWING) {
            client.sendModeCommand(DroneMode.FOLLOWING.wireValue, followMaxSpeedMps = metersPerSecond.toDouble())
        }
    }

    fun setOrbitMaxSpeed(metersPerSecond: Float) {
        _orbitMaxSpeedMps.value = metersPerSecond
        if (_mode.value == DroneMode.ORBITING) {
            client.sendModeCommand(DroneMode.ORBITING.wireValue, orbitMaxSpeedMps = metersPerSecond.toDouble())
        }
    }

    fun abort() {
        _mode.value = DroneMode.IDLE
        _showTargetActionSheet.value = false
        _stopAlerts.tryEmit(Unit)
        // Forget the selected target immediately on this side too, rather
        // than waiting for the Pi's own next tracking_update round-trip
        // (which will report the same thing, but a frame or more later) -
        // a real field request: "when I abort the mission, the selected
        // target should be forgotten too." The Pi side has a matching fix:
        // _on_abort() now also clears any pending target selection that
        // arrived just before the abort (see companion/main.py), so a
        // selection that was mid-flight can't silently re-lock a target
        // the operator just told it to forget.
        _tracking.value = TrackingState()
        _trailSnapshot.value = TrailSnapshot(emptyList(), null, null)
        client.sendAbort("operator")
    }

    /** Administrative FC command, independent of AI guidance mode - the
     * confirmation dialog before an arm request lives in the UI layer
     * (GroundStationScreen), not here. `force` is only meaningful for a
     * disarm - see GroundStationClient.sendArmCommand's docstring. */
    fun setArmed(armed: Boolean, force: Boolean = false) {
        client.sendArmCommand(armed, force)
    }

    fun setFlightMode(mode: String) {
        client.sendSetFlightMode(mode)
    }

    /** The operator's answer to a land_confirmation_request - see
     * LandConfirmationDialog.kt. Landing only ever happens on an explicit
     * true here; either answer clears the pending request. */
    fun respondToLandConfirmation(approved: Boolean) {
        client.sendLandConfirmationResponse(approved)
        _landConfirmationRequest.value = null
    }

    /** One button drives both recordings at once (by operator preference):
     * the Pi's own local recording (as before) and a local copy saved on
     * this device from the same video the operator is watching - so
     * footage survives even if only one side is reachable afterward. The
     * two are otherwise independent; a codec failure on one side doesn't
     * affect the other, matching how VideoRecorder.start() on the Pi
     * already reports failure without crashing anything. */
    fun toggleRecording() {
        val startingNow = !_recording.value.recording
        client.sendRecordCommand(startingNow)
        if (startingNow) startLocalRecording() else stopLocalRecording()
    }

    /** Builds the recording's output target - MediaStore (visible in
     * Gallery/Photos) on API 29+, or the pre-scoped-storage app-private
     * fallback on API 26-28 where MediaStore's RELATIVE_PATH/IS_PENDING
     * columns don't exist yet. See LocalVideoRecorder.kt's class docstring
     * for the real field bug ("video is not saving in mobile device") this
     * fixes - the old app-private-only path did write a valid file, just
     * somewhere no Gallery app or file manager would ever show it. */
    private fun buildLocalRecordingOutput(context: Context, displayName: String): LocalRecordingOutput? {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
            val resolver = context.contentResolver
            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.Video.Media.DISPLAY_NAME, displayName)
                put(android.provider.MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                put(
                    android.provider.MediaStore.Video.Media.RELATIVE_PATH,
                    android.os.Environment.DIRECTORY_MOVIES + "/AI Vision Drone",
                )
                put(android.provider.MediaStore.Video.Media.IS_PENDING, 1)
            }
            val uri = resolver.insert(android.provider.MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                ?: return null
            return LocalRecordingOutput.MediaStoreEntry(resolver, uri)
        }
        val dir = context.getExternalFilesDir(android.os.Environment.DIRECTORY_MOVIES) ?: context.filesDir
        dir.mkdirs()
        return LocalRecordingOutput.LegacyFile(java.io.File(dir, displayName))
    }

    private fun startLocalRecording() {
        val context = appContext ?: return
        val track = _remoteVideoTrack.value ?: return
        if (localVideoRecorder != null) return
        val output = buildLocalRecordingOutput(context, "flight_${System.currentTimeMillis()}.mp4") ?: return
        val recorder = LocalVideoRecorder(output)
        localVideoRecorder = recorder
        track.addSink(recorder)
    }

    private fun stopLocalRecording() {
        val recorder = localVideoRecorder ?: return
        localVideoRecorder = null
        _remoteVideoTrack.value?.removeSink(recorder)
        recorder.stop()
    }

    override fun onCleared() {
        disconnect()
    }

    private fun handleEnvelope(envelope: Envelope) {
        when (envelope.type) {
            MessageType.TELEMETRY -> {
                val previous = _telemetry.value
                val parsed = parseTelemetry(envelope.payload)
                emitTelemetryAlerts(previous, parsed)
                _telemetry.value = parsed
            }
            MessageType.HEALTH -> {
                val health = parseHealth(envelope.payload)
                _health.value = health
                // Seeds recording state (e.g. after a reconnect) without
                // waiting for a recording_state message the Pi has no
                // reason to resend on its own.
                if (_recording.value.recording != health.recording) {
                    _recording.value = RecordingState(recording = health.recording)
                }
            }
            MessageType.TRACKING_UPDATE -> {
                val previous = _tracking.value
                val parsed = parseTracking(envelope.payload)
                emitTrackingAlerts(previous, parsed)
                _tracking.value = parsed
                targetTrail.record(parsed)
                _trailSnapshot.value = targetTrail.snapshot(parsed.imageWidth, parsed.imageHeight)
                // A Dronie/Parabola smart shot stops itself on the Pi side
                // once its fixed duration elapses (companion/main.py resets
                // requested_mode to IDLE when it finishes) - mirror that
                // here so the mode selector doesn't keep showing the shot
                // as active after it's actually done. Deliberately not
                // done for Follow/Orbit/Approach: those can drop to SAFE
                // transiently (e.g. a brief target loss) while still
                // meaning to resume, so reverting the selector for them
                // would be misleading, not helpful.
                if (parsed.supervisorState in SAFE_OR_IDLE_STATES && _mode.value in ONE_SHOT_MODES) {
                    _mode.value = DroneMode.IDLE
                }
            }
            MessageType.DETECTIONS_UPDATE -> {
                val parsed = parseDetections(envelope.payload)
                _detections.value = parsed
                detectionHeatmap.record(parsed)
                _heatmapSnapshot.value = detectionHeatmap.snapshot()
                checkPerimeterIntrusion(parsed)
            }
            MessageType.LAND_CONFIRMATION_REQUEST -> {
                _landConfirmationRequest.value = LandConfirmationRequest(
                    distanceToHomeM = envelope.payload.optDoubleOrNull("distance_to_home_m"),
                    batteryRemainingPct = envelope.payload.optIntOrNull("battery_remaining_pct"),
                    obstacleDetected = envelope.payload.optBoolean("obstacle_detected", false),
                    obstacleClassName = envelope.payload.optStringOrNull("obstacle_class_name"),
                )
                _alertEvents.tryEmit(AlertEvent.LAND_CONFIRMATION_NEEDED)
            }
            MessageType.RECORDING_STATE -> _recording.value = RecordingState(
                recording = envelope.payload.optBoolean("recording", false),
                durationS = envelope.payload.optDoubleOrNull("duration_s") ?: 0.0,
            )
            MessageType.WEBRTC_ANSWER -> {
                envelope.payload.optStringOrNull("sdp")?.let { webRtcClient?.onRemoteAnswer(it) }
            }
        }
    }

    private fun parseTelemetry(p: JSONObject) = TelemetryState(
        flightMode = p.optStringOrNull("fc_mode"),
        armed = p.optBoolean("armed", false),
        lat = p.optDoubleOrNull("lat"),
        lon = p.optDoubleOrNull("lon"),
        altitudeM = p.optDoubleOrNull("alt_m"),
        groundspeedMps = p.optDoubleOrNull("groundspeed_mps"),
        batteryVoltage = p.optDoubleOrNull("battery_voltage_v"),
        batteryRemainingPct = p.optIntOrNull("battery_remaining_pct"),
        fenceEnabled = p.optBoolean("fence_enabled", false),
        fenceBreached = p.optBoolean("fence_breached", false),
        satellitesVisible = p.optIntOrNull("satellites_visible"),
        gpsFixType = p.optIntOrNull("gps_fix_type"),
        hdop = p.optDoubleOrNull("hdop"),
        vdop = p.optDoubleOrNull("vdop"),
        homeLat = p.optDoubleOrNull("home_lat"),
        homeLon = p.optDoubleOrNull("home_lon"),
        distanceToHomeM = p.optDoubleOrNull("distance_to_home_m"),
        homeBearingDeg = p.optDoubleOrNull("home_bearing_deg"),
        rollDeg = p.optDoubleOrNull("roll_deg"),
        pitchDeg = p.optDoubleOrNull("pitch_deg"),
        yawDeg = p.optDoubleOrNull("yaw_deg"),
        headingDeg = p.optDoubleOrNull("heading_deg"),
        airspeedMps = p.optDoubleOrNull("airspeed_mps"),
        climbMps = p.optDoubleOrNull("climb_mps"),
        throttlePct = p.optIntOrNull("throttle_pct"),
        rcRssiPct = p.optIntOrNull("rc_rssi_pct"),
        currentBatteryA = p.optDoubleOrNull("current_battery_a"),
    )

    /** Fires buzzer/voice events off real fc_mode/fence transitions - an
     * autonomous RTL is a direct FC mode change (companion/main.py's
     * target-recovery path), not its own wire message, so "just entered
     * RTL" is inferred from the mode change itself. The `previous.flightMode
     * != null` guard stops a spurious RTL_TRIGGERED firing if the FC simply
     * happens to already be in RTL when the app first connects. */
    private fun emitTelemetryAlerts(previous: TelemetryState, current: TelemetryState) {
        if (current.flightMode == "RTL" && previous.flightMode != null && previous.flightMode != "RTL") {
            _alertEvents.tryEmit(AlertEvent.RTL_TRIGGERED)
        }
        if (current.fenceBreached && !previous.fenceBreached) {
            _alertEvents.tryEmit(AlertEvent.FENCE_BREACHED)
        }
    }

    /** Fires buzzer/voice events off real tracking-lifecycle (state) and
     * guidance (supervisorState) transitions - each only on a genuine edge,
     * not every frame, since both fields are otherwise re-sent unchanged on
     * every telemetry tick. REACQUIRE (a brief, by-design transient state)
     * deliberately does not fire its own alert. */
    private fun emitTrackingAlerts(previous: TrackingState, current: TrackingState) {
        if (current.state == "TRACKING" && previous.state != "TRACKING") {
            _alertEvents.tryEmit(AlertEvent.TARGET_LOCKED)
        } else if (current.state == "TARGET_LOST" && previous.state != "TARGET_LOST") {
            _alertEvents.tryEmit(AlertEvent.TARGET_LOST)
        }

        val prevSupervisor = previous.supervisorState
        val currentSupervisor = current.supervisorState
        if (currentSupervisor != prevSupervisor) {
            when (currentSupervisor) {
                "FOLLOWING" -> _alertEvents.tryEmit(AlertEvent.FOLLOWING_ENGAGED)
                "ORBITING" -> _alertEvents.tryEmit(AlertEvent.ORBITING_ENGAGED)
                "SEARCHING" -> _alertEvents.tryEmit(AlertEvent.SEARCHING_STARTED)
                "SAFE" -> if (prevSupervisor in ACTIVE_GUIDANCE_STATES) {
                    _alertEvents.tryEmit(AlertEvent.GUIDANCE_STOPPED)
                }
            }
        }
    }

    private fun parseHealth(p: JSONObject) = HealthState(
        piOk = p.optBoolean("pi_ok", false),
        cameraOk = p.optBoolean("camera_ok", false),
        aiOk = p.optBoolean("ai_ok", false),
        trackerOk = p.optBoolean("tracker_ok", false),
        mavlinkOk = p.optBoolean("mavlink_ok", false),
        videoOk = p.optBoolean("video_ok", false),
        recording = p.optBoolean("recording", false),
        fps = p.optDoubleOrNull("fps"),
        latencyMs = p.optDoubleOrNull("latency_ms"),
        temperatureC = p.optDoubleOrNull("temperature_c"),
    )

    private fun parseTracking(p: JSONObject): TrackingState {
        val bboxJson = p.optJSONObject("bbox")
        return TrackingState(
            state = p.optString("state", "IDLE"),
            targetId = p.optIntOrNull("target_id"),
            confidence = p.optDoubleOrNull("confidence"),
            bbox = bboxJson?.let {
                TargetBBox(it.getDouble("x"), it.getDouble("y"), it.getDouble("w"), it.getDouble("h"))
            },
            imageWidth = p.optIntOrNull("image_width"),
            imageHeight = p.optIntOrNull("image_height"),
            distanceM = p.optDoubleOrNull("distance_m"),
            guidanceAllowed = p.optBoolean("guidance_allowed", false),
            guidanceReason = p.optStringOrNull("guidance_reason"),
            supervisorState = p.optStringOrNull("supervisor_state"),
            commandedVxMps = p.optDoubleOrNull("commanded_vx_mps"),
            commandedVyMps = p.optDoubleOrNull("commanded_vy_mps"),
            commandedVzMps = p.optDoubleOrNull("commanded_vz_mps"),
            commandedYawRateRads = p.optDoubleOrNull("commanded_yaw_rate_rads"),
            guidanceSent = p.optBoolean("guidance_sent", false),
        )
    }

    private fun parseDetections(p: JSONObject): DetectionsState {
        val array = p.optJSONArray("detections")
        val list = mutableListOf<RawDetection>()
        if (array != null) {
            for (i in 0 until array.length()) {
                val d = array.getJSONObject(i)
                val bboxJson = d.getJSONObject("bbox")
                list.add(
                    RawDetection(
                        bbox = TargetBBox(
                            bboxJson.getDouble("x"), bboxJson.getDouble("y"),
                            bboxJson.getDouble("w"), bboxJson.getDouble("h"),
                        ),
                        className = d.getString("class_name"),
                        score = d.getDouble("score"),
                    )
                )
            }
        }
        return DetectionsState(
            imageWidth = p.optIntOrNull("image_width"),
            imageHeight = p.optIntOrNull("image_height"),
            detections = list,
        )
    }
}
