package com.aivisiondrone.groundstation.comms

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

enum class LinkState { DISCONNECTED, CONNECTING, CONNECTED }

private const val HEARTBEAT_PERIOD_MS = 500L

/**
 * Control/telemetry channel to the Pi's GroundStationLink (companion/comms/ws_server.py).
 * Kept separate from video (WebRtcClient) so a video hiccup never blocks an abort command -
 * see docs plan M5/M6.
 */
class GroundStationClient(
    // OkHttp's own WebSocket ping (default: none) lets the app notice a dead Pi
    // link within seconds instead of waiting on the OS's TCP timeout.
    private val client: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(2, TimeUnit.SECONDS)
        .build(),
) {
    private var socket: WebSocket? = null

    // The Pi treats this app as gone (and stops all guidance) if it hears
    // nothing for comms_timeout_s - a TCP socket can look open long after a
    // WiFi link has died, so liveness is judged from real traffic. A tiny
    // application-level ping every 500ms is that traffic; the Pi's pong reply
    // is ignored. Runs only while the socket is open.
    private val heartbeatExecutor = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "gs-heartbeat").apply { isDaemon = true }
    }
    private var heartbeat: ScheduledFuture<*>? = null

    private fun startHeartbeat(webSocket: WebSocket) {
        stopHeartbeat()
        heartbeat = heartbeatExecutor.scheduleAtFixedRate(
            { runCatching { webSocket.send(makeEnvelope(MessageType.PING, JSONObject()).toJson()) } },
            0, HEARTBEAT_PERIOD_MS, TimeUnit.MILLISECONDS,
        )
    }

    private fun stopHeartbeat() {
        heartbeat?.cancel(false)
        heartbeat = null
    }

    private val _linkState = MutableStateFlow(LinkState.DISCONNECTED)
    val linkState = _linkState.asStateFlow()

    private val _messages = MutableSharedFlow<Envelope>(extraBufferCapacity = 64)
    val messages = _messages.asSharedFlow()

    /** Set false by an explicit disconnect(); read by MainViewModel to decide
     * whether a dropped link should be auto-retried. */
    var shouldAutoReconnect: Boolean = false
        private set

    private var lastHost: String? = null
    private var lastPort: Int? = null

    fun connect(host: String, port: Int) {
        lastHost = host
        lastPort = port
        shouldAutoReconnect = true
        _linkState.value = LinkState.CONNECTING
        val request = Request.Builder().url("ws://$host:$port").build()
        socket = client.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    _linkState.value = LinkState.CONNECTED
                    startHeartbeat(webSocket)
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { Envelope.fromJson(text) }.onSuccess { _messages.tryEmit(it) }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    stopHeartbeat()
                    _linkState.value = LinkState.DISCONNECTED
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    stopHeartbeat()
                    _linkState.value = LinkState.DISCONNECTED
                }
            },
        )
    }

    /** Re-attempts the last connect() with the same host/port - used for
     * auto-reconnect after an unexpected drop, not the first connection. */
    fun reconnect() {
        val host = lastHost ?: return
        val port = lastPort ?: return
        connect(host, port)
    }

    fun disconnect() {
        shouldAutoReconnect = false
        stopHeartbeat()
        socket?.close(1000, "client disconnect")
        socket = null
        _linkState.value = LinkState.DISCONNECTED
    }

    private fun send(type: String, payload: JSONObject) {
        socket?.send(makeEnvelope(type, payload).toJson())
    }

    fun sendTargetSelect(x: Double, y: Double, w: Double, h: Double) {
        send(
            MessageType.TARGET_SELECT,
            JSONObject().apply {
                put("x", x)
                put("y", y)
                put("w", w)
                put("h", h)
            },
        )
    }

    /** Tap-to-select: the Pi matches this point against its own current
     * detections (whichever box contains it), rather than requiring the
     * operator to drag out a selection rectangle. */
    fun sendTargetSelectAtPoint(x: Double, y: Double) {
        send(
            MessageType.TARGET_SELECT,
            JSONObject().apply {
                put("x", x)
                put("y", y)
                put("point", true)
            },
        )
    }

    fun sendModeCommand(
        mode: String,
        followSeparationM: Double? = null,
        followAltitudeM: Double? = null,
        orbitRadiusM: Double? = null,
        orbitAltitudeM: Double? = null,
        followMaxSpeedMps: Double? = null,
        orbitMaxSpeedMps: Double? = null,
        gridSearchWidthM: Double? = null,
        gridSearchHeightM: Double? = null,
        gridSearchHeadingDeg: Double? = null,
        autoTakeoff: Boolean = false,
    ) {
        val payload = JSONObject().put("mode", mode)
        if (followSeparationM != null) payload.put("follow_separation_m", followSeparationM)
        if (followAltitudeM != null) payload.put("follow_altitude_m", followAltitudeM)
        if (orbitRadiusM != null) payload.put("orbit_radius_m", orbitRadiusM)
        if (orbitAltitudeM != null) payload.put("orbit_altitude_m", orbitAltitudeM)
        if (followMaxSpeedMps != null) payload.put("follow_max_speed_mps", followMaxSpeedMps)
        if (orbitMaxSpeedMps != null) payload.put("orbit_max_speed_mps", orbitMaxSpeedMps)
        // Only required to actually start a fresh sweep - the Pi plans it
        // from wherever the aircraft currently is at the moment it handles
        // this message (companion/main.py's _on_mode_command), so no
        // lat/lon is sent from here at all.
        if (gridSearchWidthM != null) payload.put("grid_search_width_m", gridSearchWidthM)
        if (gridSearchHeightM != null) payload.put("grid_search_height_m", gridSearchHeightM)
        if (gridSearchHeadingDeg != null) payload.put("grid_search_heading_deg", gridSearchHeadingDeg)
        // "Arm & Follow should gain height, then start following" - tells
        // the Pi to hold off on real Follow guidance until AutoTakeoffController
        // finishes climbing to a safe altitude (companion/guidance/auto_takeoff.py).
        // Only ever true from armAndFollow(); a plain mode switch once
        // already airborne has no reason to set this.
        if (autoTakeoff) payload.put("auto_takeoff", true)
        send(MessageType.MODE_COMMAND, payload)
    }

    fun sendAbort(reason: String) {
        send(MessageType.ABORT, JSONObject().put("reason", reason))
    }

    /** Administrative FC command - arm/disarm goes straight to the flight
     * controller like a standard GCS, independent of AI guidance state.
     * `force` is only meaningful for a disarm - see docs/protocol.md and
     * MavlinkBridge.arm()'s docstring: ArduCopter refuses a normal disarm
     * outright if its land-detector thinks it's flying, which a bench test
     * with props spinning can trip as a false positive. */
    fun sendArmCommand(armed: Boolean, force: Boolean = false) {
        val payload = JSONObject().put("armed", armed)
        if (force) payload.put("force", true)
        send(MessageType.ARM_COMMAND, payload)
    }

    fun sendSetFlightMode(mode: String) {
        send(MessageType.SET_FLIGHT_MODE, JSONObject().put("mode", mode))
    }

    fun sendRecordCommand(recording: Boolean) {
        send(MessageType.RECORD_COMMAND, JSONObject().put("recording", recording))
    }

    /** The operator's answer to a land_confirmation_request (target-loss
     * recovery timed out with low battery/too far to RTL - see
     * companion/guidance/target_recovery.py). Landing only ever happens on
     * an explicit true here. */
    fun sendLandConfirmationResponse(approved: Boolean) {
        send(MessageType.LAND_CONFIRMATION_RESPONSE, JSONObject().put("approved", approved))
    }

    fun sendWebRtcOffer(sdp: String, sdpType: String) {
        send(
            MessageType.WEBRTC_OFFER,
            JSONObject().apply {
                put("sdp", sdp)
                put("sdp_type", sdpType)
            },
        )
    }
}
