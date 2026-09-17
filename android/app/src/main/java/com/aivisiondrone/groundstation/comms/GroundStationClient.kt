package com.aivisiondrone.groundstation.comms

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

enum class LinkState { DISCONNECTED, CONNECTING, CONNECTED }

/**
 * Control/telemetry channel to the Pi's GroundStationLink (companion/comms/ws_server.py).
 * Kept separate from video (WebRtcClient) so a video hiccup never blocks an abort command -
 * see docs plan M5/M6.
 */
class GroundStationClient(private val client: OkHttpClient = OkHttpClient()) {
    private var socket: WebSocket? = null

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
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { Envelope.fromJson(text) }.onSuccess { _messages.tryEmit(it) }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    _linkState.value = LinkState.DISCONNECTED
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
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
    ) {
        val payload = JSONObject().put("mode", mode)
        if (followSeparationM != null) payload.put("follow_separation_m", followSeparationM)
        if (followAltitudeM != null) payload.put("follow_altitude_m", followAltitudeM)
        if (orbitRadiusM != null) payload.put("orbit_radius_m", orbitRadiusM)
        if (orbitAltitudeM != null) payload.put("orbit_altitude_m", orbitAltitudeM)
        send(MessageType.MODE_COMMAND, payload)
    }

    fun sendAbort(reason: String) {
        send(MessageType.ABORT, JSONObject().put("reason", reason))
    }

    /** Administrative FC command - arm/disarm goes straight to the flight
     * controller like a standard GCS, independent of AI guidance state. */
    fun sendArmCommand(armed: Boolean) {
        send(MessageType.ARM_COMMAND, JSONObject().put("armed", armed))
    }

    fun sendSetFlightMode(mode: String) {
        send(MessageType.SET_FLIGHT_MODE, JSONObject().put("mode", mode))
    }

    fun sendRecordCommand(recording: Boolean) {
        send(MessageType.RECORD_COMMAND, JSONObject().put("recording", recording))
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
