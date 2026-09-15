package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.telemetry.TrackingState

/**
 * Draws the tracker's bounding box (scaled from the Pi's reported video
 * resolution to this overlay's actual on-screen size) plus target id and
 * confidence, per docs plan M6.
 */
@Composable
fun TrackingOverlay(tracking: TrackingState, modifier: Modifier = Modifier) {
    val bbox = tracking.bbox
    val srcWidth = tracking.imageWidth
    val srcHeight = tracking.imageHeight

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
            }
        }

        if (tracking.targetId != null) {
            Text(
                text = "TARGET #${tracking.targetId}  ${tracking.state}" +
                    (tracking.confidence?.let { "  ${(it * 100).toInt()}%" } ?: "") +
                    (tracking.distanceM?.let { "  %.1fm".format(it) } ?: ""),
                color = Color.White,
                modifier = Modifier.align(Alignment.TopStart).padding(8.dp),
            )
        }
    }
}
