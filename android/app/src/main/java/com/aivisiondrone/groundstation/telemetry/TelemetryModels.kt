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
    // From a real GPS_RAW_INT message - satellitesVisible is null when the
    // FC reports the standard "unknown" sentinel (255), not zero satellites.
    // gpsFixType follows MAV_GPS_FIX_TYPE (0/1 = no fix, 2 = 2D, 3+ = 3D or
    // better) - the authoritative GPS health signal, previously only
    // inferred (imprecisely) from lat being non-null.
    val satellitesVisible: Int? = null,
    val gpsFixType: Int? = null,
    // From real GPS_RAW_INT.eph/epv - null on the standard 65535 "unknown"
    // sentinel (companion/mavlink/bridge.py).
    val hdop: Double? = null,
    val vdop: Double? = null,
    val homeLat: Double? = null,
    val homeLon: Double? = null,
    // Computed on the Pi from a real HOME_POSITION + the current GPS fix
    // (companion/guidance/geo.py) - both null until home is known.
    val distanceToHomeM: Double? = null,
    val homeBearingDeg: Double? = null,
    // From a real ATTITUDE message (degrees).
    val rollDeg: Double? = null,
    val pitchDeg: Double? = null,
    val yawDeg: Double? = null,
    // From a real VFR_HUD message.
    val headingDeg: Double? = null,
    val airspeedMps: Double? = null,
    val climbMps: Double? = null,
    val throttlePct: Int? = null,
    // From RC_CHANNELS.rssi rescaled to 0-100% - null on the standard 255
    // "unknown" sentinel.
    val rcRssiPct: Int? = null,
    val currentBatteryA: Double? = null,
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
    // TRACKING, FOLLOWING, ORBITING, APPROACHING, GRID_SEARCH, SAFE) - used
    // to notice when the Pi has dropped out of a guidance mode on its own
    // (a finished sweep, an Approach-Test boundary stop, a forced SAFE) so
    // the mode selector can reflect reality instead of staying stuck on
    // whatever the operator last tapped.
    val supervisorState: String? = null,
    // The active guidance controller's computed velocity setpoint this
    // frame (null when none is running) and whether it actually reached
    // the FC (guidanceSent is false if the Safety Supervisor blocked it) -
    // meant to be watched live during a props-off bench test, per the
    // plan's staged real-flight procedure, not just reviewed after the
    // fact from the Pi's session log.
    val commandedVxMps: Double? = null,
    val commandedVyMps: Double? = null,
    val commandedVzMps: Double? = null,
    val commandedYawRateRads: Double? = null,
    val guidanceSent: Boolean = false,
    // Why guidance is deliberately holding still even though the Safety
    // Supervisor allows it (companion/main.py): "auto_takeoff" (climbing to a
    // safe altitude first), "target_unseen" (briefly out of sight - holds
    // rather than steering on stale coordinates), "identity_lost" (the tracked
    // subject stopped looking like the selected target). null = not holding.
    val guidanceHold: String? = null,
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

/** Target-loss recovery's search timed out and battery/distance say
 * landing in place is safer than RTL (companion/guidance/target_recovery.py).
 * obstacleDetected/obstacleClassName are informational only - the operator
 * makes the actual land/don't-land call, this never auto-decides. Present
 * (non-null) in MainViewModel's state exactly while awaiting a response;
 * answering it (either way) clears it back to null. */
data class LandConfirmationRequest(
    val distanceToHomeM: Double? = null,
    val batteryRemainingPct: Int? = null,
    val obstacleDetected: Boolean = false,
    val obstacleClassName: String? = null,
)

data class LatLon(val lat: Double, val lon: Double)

/** Grid/lawnmower area-sweep search mode (companion/guidance/grid_search.py) -
 * a field request extending the existing single-target yaw-sweep search
 * into deliberate area coverage. Sent every frame regardless of mode
 * (mirroring detections_update/tracking_update), so the live map always
 * has current state without needing a separate one-shot "final" message. */
data class GridSearchState(
    val active: Boolean = false,
    val phase: String = "IDLE",
    val waypoints: List<LatLon> = emptyList(),
    val currentIndex: Int = 0,
)
