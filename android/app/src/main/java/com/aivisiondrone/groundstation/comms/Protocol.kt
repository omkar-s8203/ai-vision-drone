package com.aivisiondrone.groundstation.comms

import org.json.JSONObject

/** Mirrors companion/comms/protocol.py's MessageType exactly - keep both in sync. */
object MessageType {
    const val TARGET_SELECT = "target_select"
    const val MODE_COMMAND = "mode_command"
    const val ABORT = "abort"
    const val TRACKING_UPDATE = "tracking_update"
    const val TELEMETRY = "telemetry"
    const val HEALTH = "health"
    const val ACK = "ack"
    const val ERROR = "error"
    const val WEBRTC_OFFER = "webrtc_offer"
    const val WEBRTC_ANSWER = "webrtc_answer"
}

data class Envelope(
    val type: String,
    val seq: Int,
    val ts: Double,
    val payload: JSONObject,
) {
    fun toJson(): String =
        JSONObject().apply {
            put("type", type)
            put("seq", seq)
            put("ts", ts)
            put("payload", payload)
        }.toString()

    companion object {
        fun fromJson(raw: String): Envelope {
            val obj = JSONObject(raw)
            return Envelope(
                type = obj.getString("type"),
                seq = obj.getInt("seq"),
                ts = obj.getDouble("ts"),
                payload = obj.optJSONObject("payload") ?: JSONObject(),
            )
        }
    }
}

private var sequenceCounter = 0

fun makeEnvelope(type: String, payload: JSONObject): Envelope {
    sequenceCounter += 1
    return Envelope(
        type = type,
        seq = sequenceCounter,
        ts = System.currentTimeMillis() / 1000.0,
        payload = payload,
    )
}
