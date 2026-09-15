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
)

data class HealthState(
    val piOk: Boolean = false,
    val cameraOk: Boolean = false,
    val aiOk: Boolean = false,
    val trackerOk: Boolean = false,
    val mavlinkOk: Boolean = false,
    val videoOk: Boolean = false,
    val fps: Double? = null,
    val latencyMs: Double? = null,
    val temperatureC: Double? = null,
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
)
