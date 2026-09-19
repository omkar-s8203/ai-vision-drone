package com.aivisiondrone.groundstation.control

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.unit.coerceAtLeast
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.telemetry.TrackingState
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

    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            if (bbox != null && srcWidth != null && srcHeight != null && srcWidth > 0 && srcHeight > 0) {
                val scaleX = size.width / srcWidth
                val scaleY = size.height / srcHeight
                val topLeft = Offset((bbox.x * scaleX).toFloat(), (bbox.y * scaleY).toFloat())
                val boxSize = Size((bbox.w * scaleX).toFloat(), (bbox.h * scaleY).toFloat())
                
                val statusColor = when (tracking.state) {
                    "TRACKING" -> DroneColors.Accent
                    "REACQUIRE" -> DroneColors.Warning
                    else -> DroneColors.Danger
                }

                // Modern Corner Brackets
                val bracketLen = 20f
                val strokeWidth = 6f
                
                // Top-Left
                drawLine(statusColor, topLeft, topLeft.copy(x = topLeft.x + bracketLen), strokeWidth)
                drawLine(statusColor, topLeft, topLeft.copy(y = topLeft.y + bracketLen), strokeWidth)
                
                // Top-Right
                val topRight = topLeft.copy(x = topLeft.x + boxSize.width)
                drawLine(statusColor, topRight, topRight.copy(x = topRight.x - bracketLen), strokeWidth)
                drawLine(statusColor, topRight, topRight.copy(y = topRight.y + bracketLen), strokeWidth)
                
                // Bottom-Left
                val bottomLeft = topLeft.copy(y = topLeft.y + boxSize.height)
                drawLine(statusColor, bottomLeft, bottomLeft.copy(x = bottomLeft.x + bracketLen), strokeWidth)
                drawLine(statusColor, bottomLeft, bottomLeft.copy(y = bottomLeft.y - bracketLen), strokeWidth)
                
                // Bottom-Right
                val bottomRight = topLeft.copy(x = topLeft.x + boxSize.width, y = topLeft.y + boxSize.height)
                drawLine(statusColor, bottomRight, bottomRight.copy(x = bottomRight.x - bracketLen), strokeWidth)
                drawLine(statusColor, bottomRight, bottomRight.copy(y = bottomRight.y - bracketLen), strokeWidth)

                if (orbiting) {
                    val center = Offset(topLeft.x + boxSize.width / 2f, topLeft.y + boxSize.height / 2f)
                    val radius = max(boxSize.width, boxSize.height) * 0.9f
                    rotate(degrees = rotationDeg, pivot = center) {
                        drawCircle(
                            color = DroneColors.Accent,
                            radius = radius,
                            center = center,
                            style = Stroke(
                                width = 3f,
                                pathEffect = PathEffect.dashPathEffect(floatArrayOf(30f, 20f)),
                            ),
                        )
                    }
                }
            }
        }

        if (tracking.targetId != null && bbox != null && srcWidth != null && srcHeight != null && srcWidth > 0 && srcHeight > 0) {
            val relX = (bbox.x / srcWidth).toFloat()
            val relY = (bbox.y / srcHeight).toFloat()
            val topLeftX = maxWidth * relX
            val topLeftY = maxHeight * relY
            
            Text(
                text = "LOCKED #${tracking.targetId}",
                color = DroneColors.Accent,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = androidx.compose.ui.text.font.FontWeight.ExtraBold,
                modifier = Modifier
                    .padding(
                        start = topLeftX.coerceAtLeast(0.dp),
                        top = (topLeftY - 20.dp).coerceAtLeast(0.dp)
                    )
                    .background(DroneColors.Overlay, RoundedCornerShape(4.dp))
                    .padding(horizontal = 4.dp, vertical = 2.dp)
            )
        }
    }
}
