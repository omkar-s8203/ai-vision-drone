package com.aivisiondrone.groundstation.telemetry

data class TelemetryState(
    val flightMode: String? = null,
    val armed: Boolean = false,
    val lat: Double? = null,
    val lon: Double? = null,
    val altitudeM: Double? = null,
    val groundspeedMps: Double? = null,
    val batteryVoltage: Double? = null,
    val batteryRemainingPct: Int? = null,
    // From the FC's real SYS_STATUS geofence bit (companion/mavlink/bridge.py) -
    // fenceBreached only means anything when fenceEnabled is true.
    val fenceEnabled: Boolean = false,
    val fenceBreached: Boolean = false,
)

data class HealthState(
    val piOk: Boolean = false,
    val cameraOk: Boolean = false,
    val aiOk: Boolean = false,
    val trackerOk: Boolean = false,
    val mavlinkOk: Boolean = false,
    val videoOk: Boolean = false,
    val recording: Boolean = false,
    val fps: Double? = null,
    val latencyMs: Double? = null,
    val temperatureC: Double? = null,
)

/** Local recording indicator - seeded from the health payload's `recording`
 * flag on (re)connect, then kept live by dedicated recording_state messages
 * so the duration counter updates without waiting for the next health tick. */
data class RecordingState(
    val recording: Boolean = false,
    val durationS: Double = 0.0,
)

data class TargetBBox(val x: Double, val y: Double, val w: Double, val h: Double)

data class TrackingState(
    val state: String = "IDLE",
    val targetId: Int? = null,
    val confidence: Double? = null,
    val bbox: TargetBBox? = null,
    val imageWidth: Int? = null,
    val imageHeight: Int? = null,
    val distanceM: Double? = null,
    val guidanceAllowed: Boolean = false,
    val guidanceReason: String? = null,
    // Mirrors companion/safety/supervisor.py's SupervisorState name (IDLE,
    // TRACKING, FOLLOWING, ORBITING, APPROACHING, SMART_SHOT, SAFE) - used
    // to notice when the Pi has dropped out of a guidance mode on its own
    // (a finished smart shot, an Approach-Test boundary stop, a forced
    // SAFE) so the mode selector can reflect reality instead of staying
    // stuck on whatever the operator last tapped.
    val supervisorState: String? = null,
)

/** One live object detection before/independent of target selection - lets
 * the operator see everything the AI can detect and tap one to select it. */
data class RawDetection(
    val bbox: TargetBBox,
    val className: String,
    val score: Double,
)

data class DetectionsState(
    val imageWidth: Int? = null,
    val imageHeight: Int? = null,
    val detections: List<RawDetection> = emptyList(),
)
