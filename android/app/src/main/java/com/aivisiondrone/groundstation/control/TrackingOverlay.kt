package com.aivisiondrone.groundstation.control

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import kotlin.math.max

/**
 * Draws the tracker's bounding box (scaled from the Pi's reported video
 * resolution to this overlay's actual on-screen size) plus target id and
 * confidence, per docs plan M6. When `orbiting` is true, also draws a
 * rotating dashed circle around the target - the DJI "circle shot" visual
 * cue that the drone is actively orbiting this subject.
 */
@Composable
fun TrackingOverlay(tracking: TrackingState, orbiting: Boolean = false, modifier: Modifier = Modifier) {
    val bbox = tracking.bbox
    val srcWidth = tracking.imageWidth
    val srcHeight = tracking.imageHeight

    val transition = rememberInfiniteTransition(label = "orbit-ring")
    val rotationDeg by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(4000, easing = LinearEasing)),
        label = "orbit-ring-rotation",
    )

    Box(modifier = modifier.fillMaxSize()) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            if (bbox != null && srcWidth != null && srcHeight != null && srcWidth > 0 && srcHeight > 0) {
                val scaleX = size.width / srcWidth
                val scaleY = size.height / srcHeight
                val topLeft = Offset((bbox.x * scaleX).toFloat(), (bbox.y * scaleY).toFloat())
                val boxSize = Size((bbox.w * scaleX).toFloat(), (bbox.h * scaleY).toFloat())
                val color = when (tracking.state) {
                    "TRACKING" -> Color.Green
                    "REACQUIRE" -> Color.Yellow
                    else -> Color.Red
                }
                drawRect(color = color, topLeft = topLeft, size = boxSize, style = Stroke(width = 4f))

                if (orbiting) {
                    val center = Offset(topLeft.x + boxSize.width / 2f, topLeft.y + boxSize.height / 2f)
                    val radius = max(boxSize.width, boxSize.height) * 0.9f
                    rotate(degrees = rotationDeg, pivot = center) {
                        drawCircle(
                            color = DroneColors.Accent,
                            radius = radius,
                            center = center,
                            style = Stroke(
                                width = 5f,
                                pathEffect = PathEffect.dashPathEffect(floatArrayOf(24f, 18f)),
                            ),
                        )
                    }
                }
            }
        }

        if (tracking.targetId != null) {
            Text(
                text = "TARGET #${tracking.targetId}  ${tracking.state}" +
                    (tracking.confidence?.let { "  ${(it * 100).toInt()}%" } ?: "") +
                    (tracking.distanceM?.let { "  %.1fm".format(it) } ?: "") +
                    (if (orbiting) "  ORBITING" else ""),
                color = Color.White,
                modifier = Modifier.align(Alignment.TopStart).padding(8.dp),
            )
        }
    }
}
