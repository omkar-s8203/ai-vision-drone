package com.aivisiondrone.groundstation.control

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import com.aivisiondrone.groundstation.telemetry.TargetBBox

/**
 * Draws the operator-defined perimeter/intrusion zone at all times (once
 * set), scaled from the Pi's reported video coordinate space the same way
 * TrackingOverlay/DetectionsOverlay already do. A dashed orange outline
 * normally; solid, pulsing red while `breached` is true (a detection is
 * currently inside it) so the visual state matches the buzzer firing -
 * see MainViewModel.checkPerimeterIntrusion() and AlertEvent.
 * PERIMETER_BREACHED/PERIMETER_CLEARED.
 */
@Composable
fun PerimeterZoneOverlay(
    zone: TargetBBox?,
    breached: Boolean,
    imageWidth: Int?,
    imageHeight: Int?,
    modifier: Modifier = Modifier,
) {
    val transition = rememberInfiniteTransition(label = "perimeter-breach-pulse")
    val pulseAlpha by transition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(500), repeatMode = RepeatMode.Reverse),
        label = "perimeter-breach-pulse-alpha",
    )

    Canvas(modifier = modifier.fillMaxSize()) {
        if (zone == null || imageWidth == null || imageHeight == null || imageWidth <= 0 || imageHeight <= 0) {
            return@Canvas
        }
        val scaleX = size.width / imageWidth
        val scaleY = size.height / imageHeight
        val topLeft = Offset((zone.x * scaleX).toFloat(), (zone.y * scaleY).toFloat())
        val zoneSize = Size((zone.w * scaleX).toFloat(), (zone.h * scaleY).toFloat())

        if (breached) {
            drawRect(
                color = Color(0xFFFF1744).copy(alpha = pulseAlpha),
                topLeft = topLeft,
                size = zoneSize,
                style = Stroke(width = 6f),
            )
        } else {
            drawRect(
                color = Color(0xFFFF6D00).copy(alpha = 0.8f),
                topLeft = topLeft,
                size = zoneSize,
                style = Stroke(width = 3f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(24f, 14f))),
            )
        }
    }
}
