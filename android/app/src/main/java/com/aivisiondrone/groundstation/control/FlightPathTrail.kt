package com.aivisiondrone.groundstation.control

import com.aivisiondrone.groundstation.telemetry.LatLon

// A ring buffer, not an ever-growing list - bounds memory and keeps the
// rendered path readable over a long flight, the same design as
// TargetTrail.kt's target-movement trail.
private const val MAX_PATH_POINTS = 500

/**
 * Accumulates the aircraft's own GPS track over the session - fed from
 * every real `telemetry` message (not `tracking_update`; this is the
 * aircraft's own position, orthogonal to whatever it's tracking). Backs
 * FlightMapView's flight-path polyline, part of a field request for a
 * live map view (drone position, home, flight path).
 *
 * Deliberately plain Kotlin, no Compose dependency - MainViewModel owns
 * one, updates it as telemetry arrives, and exposes immutable snapshots
 * via StateFlow for the UI to render, the same pattern as
 * DetectionHeatmap/TargetTrail.
 */
class FlightPathTrail {
    private val points = ArrayDeque<LatLon>()

    fun record(lat: Double?, lon: Double?) {
        if (lat == null || lon == null) return
        val last = points.lastOrNull()
        if (last != null && last.lat == lat && last.lon == lon) return  // stationary - nothing new to plot
        points.addLast(LatLon(lat, lon))
        while (points.size > MAX_PATH_POINTS) points.removeFirst()
    }

    fun snapshot(): List<LatLon> = points.toList()
}
