package com.aivisiondrone.groundstation.control

import com.aivisiondrone.groundstation.telemetry.TrackingState

// A ring buffer, not an ever-growing list - bounds memory and keeps the
// rendered trail readable during a long tracking session instead of
// smearing into an unreadable tangle. ~a few seconds of history at typical
// tracking_update rates (up to the camera's target FPS).
private const val MAX_TRAIL_POINTS = 60

/** One recorded point along the tracked target's movement trail - the
 * target bbox's center, in the Pi's own reported video coordinate space
 * (not screen pixels; TargetTrailOverlay rescales the same way
 * TrackingOverlay already does for the bounding box itself). */
data class TrailPoint(val x: Double, val y: Double)

data class TrailSnapshot(val points: List<TrailPoint>, val imageWidth: Int?, val imageHeight: Int?)

/**
 * Tracks the currently-locked target's recent movement path across the
 * frame - a field request: "add visual patterns / spatial patterns
 * feature," clarified as a target movement trail (as opposed to
 * DetectionHeatmap's all-objects density map). Cleared whenever tracking
 * restarts on a different target or the target is lost, so the trail
 * always reflects "this specific tracking session's" path, never a smear
 * across unrelated targets or a stale trail left over after a target was
 * lost and a new one selected.
 *
 * Deliberately plain Kotlin, no Compose dependency - MainViewModel owns
 * one, updates it as TRACKING_UPDATE messages arrive, and exposes
 * immutable TrailSnapshot copies via StateFlow for the UI to render
 * (TargetTrailOverlay.kt), the same pattern as DetectionHeatmap.
 */
class TargetTrail {
    private val points = ArrayDeque<TrailPoint>()
    private var lastTargetId: Int? = null

    fun record(tracking: TrackingState) {
        val targetId = tracking.targetId
        val bbox = tracking.bbox
        if (targetId == null || bbox == null) {
            points.clear()
            lastTargetId = null
            return
        }
        if (targetId != lastTargetId) {
            points.clear()
            lastTargetId = targetId
        }
        points.addLast(TrailPoint(bbox.x + bbox.w / 2.0, bbox.y + bbox.h / 2.0))
        while (points.size > MAX_TRAIL_POINTS) points.removeFirst()
    }

    fun snapshot(imageWidth: Int?, imageHeight: Int?): TrailSnapshot =
        TrailSnapshot(points.toList(), imageWidth, imageHeight)
}
