package com.aivisiondrone.groundstation

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aivisiondrone.groundstation.comms.Envelope
import com.aivisiondrone.groundstation.comms.GroundStationClient
import com.aivisiondrone.groundstation.comms.MessageType
import com.aivisiondrone.groundstation.comms.optDoubleOrNull
import com.aivisiondrone.groundstation.comms.optIntOrNull
import com.aivisiondrone.groundstation.comms.optStringOrNull
import com.aivisiondrone.groundstation.control.DroneMode
import com.aivisiondrone.groundstation.telemetry.DetectionsState
import com.aivisiondrone.groundstation.telemetry.HealthState
import com.aivisiondrone.groundstation.telemetry.RawDetection
import com.aivisiondrone.groundstation.telemetry.RecordingState
import com.aivisiondrone.groundstation.telemetry.TargetBBox
import com.aivisiondrone.groundstation.telemetry.TelemetryState
import com.aivisiondrone.groundstation.telemetry.TrackingState
import com.aivisiondrone.groundstation.video.WebRtcClient
import com.aivisiondrone.groundstation.comms.LinkState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.webrtc.EglBase
import org.webrtc.VideoTrack

private const val RECONNECT_DELAY_MS = 3000L

/**
 * Ties the WebSocket control/telemetry channel and the WebRTC video channel
 * together into the state the Compose UI renders (docs plan M6). Video and
 * comms stay on separate underlying transports so a video hiccup never
 * blocks an abort command.
 */
class MainViewModel : ViewModel() {
    private val client = GroundStationClient()
    private var webRtcClient: WebRtcClient? = null

    val linkState = client.linkState

    private val _telemetry = MutableStateFlow(TelemetryState())
    val telemetry = _telemetry.asStateFlow()

    private val _health = MutableStateFlow(HealthState())
    val health = _health.asStateFlow()

    private val _tracking = MutableStateFlow(TrackingState())
    val tracking = _tracking.asStateFlow()

    private val _detections = MutableStateFlow(DetectionsState())
    val detections = _detections.asStateFlow()

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

    private val _recording = MutableStateFlow(RecordingState())
    val recording = _recording.asStateFlow()

    /** True right after a tap-select, until the operator picks Track/
     * Follow/Orbit (or cancels) from the DJI-style quick action sheet. */
    private val _showTargetActionSheet = MutableStateFlow(false)
    val showTargetActionSheet = _showTargetActionSheet.asStateFlow()

    private val _remoteVideoTrack = MutableStateFlow<VideoTrack?>(null)
    val remoteVideoTrack = _remoteVideoTrack.asStateFlow()

    init {
        viewModelScope.launch {
            client.messages.collect { envelope -> handleEnvelope(envelope) }
        }
        viewModelScope.launch {
            client.linkState.collect { state ->
                if (state == LinkState.DISCONNECTED && client.shouldAutoReconnect) {
                    delay(RECONNECT_DELAY_MS)
                    if (client.shouldAutoReconnect) {
                        client.reconnect()
                    }
                }
            }
        }
    }

    fun connect(context: Context, eglBase: EglBase, host: String, port: Int) {
        client.connect(host, port)
        if (webRtcClient == null) {
            webRtcClient = WebRtcClient(
                context = context,
                eglBase = eglBase,
                onLocalOffer = { sdp, type -> client.sendWebRtcOffer(sdp, type) },
                onRemoteVideoTrack = { track -> _remoteVideoTrack.value = track },
            ).also { it.startReceiving() }
        }
    }

    fun disconnect() {
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
        client.sendModeCommand(newMode.wireValue, separation, followAltitude, orbitRadius, orbitAltitude)
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

    fun abort() {
        _mode.value = DroneMode.IDLE
        _showTargetActionSheet.value = false
        client.sendAbort("operator")
    }

    /** Administrative FC command, independent of AI guidance mode - the
     * confirmation dialog before an arm request lives in the UI layer
     * (GroundStationScreen), not here. */
    fun setArmed(armed: Boolean) {
        client.sendArmCommand(armed)
    }

    fun setFlightMode(mode: String) {
        client.sendSetFlightMode(mode)
    }

    fun toggleRecording() {
        client.sendRecordCommand(!_recording.value.recording)
    }

    override fun onCleared() {
        disconnect()
    }

    private fun handleEnvelope(envelope: Envelope) {
        when (envelope.type) {
            MessageType.TELEMETRY -> _telemetry.value = parseTelemetry(envelope.payload)
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
            MessageType.TRACKING_UPDATE -> _tracking.value = parseTracking(envelope.payload)
            MessageType.DETECTIONS_UPDATE -> _detections.value = parseDetections(envelope.payload)
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
    )

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
