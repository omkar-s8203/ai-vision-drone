package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * Draws the tracked target's recent movement path as a fading trail -
 * oldest points near-transparent, the newest segment fully opaque - so the
 * operator can see at a glance whether the subject is moving steadily,
 * pacing back and forth, or circling, without needing to have watched the
 * whole session. Purely a visualization on top of TrackingOverlay's own
 * bounding box; it never feeds back into tracking/guidance.
 */
@Composable
fun TargetTrailOverlay(snapshot: TrailSnapshot, modifier: Modifier = Modifier) {
    val srcWidth = snapshot.imageWidth
    val srcHeight = snapshot.imageHeight

    Canvas(modifier = modifier.fillMaxSize()) {
        if (srcWidth == null || srcHeight == null || srcWidth <= 0 || srcHeight <= 0) return@Canvas
        val points = snapshot.points
        if (points.size < 2) return@Canvas

        val scaleX = size.width / srcWidth
        val scaleY = size.height / srcHeight
        val segmentCount = points.size - 1

        for (i in 0 until segmentCount) {
            val from = points[i]
            val to = points[i + 1]
            // Oldest segment is barely visible, newest is fully opaque -
            // a simple linear ramp keyed on position in the trail.
            val progress = (i + 1).toFloat() / segmentCount
            val alpha = 0.12f + 0.65f * progress
            drawLine(
                color = DroneColors.Accent.copy(alpha = alpha),
                start = Offset((from.x * scaleX).toFloat(), (from.y * scaleY).toFloat()),
                end = Offset((to.x * scaleX).toFloat(), (to.y * scaleY).toFloat()),
                strokeWidth = 4f,
                cap = StrokeCap.Round,
            )
        }
    }
}
