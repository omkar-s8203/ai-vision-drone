package com.aivisiondrone.groundstation.control

import android.graphics.Paint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import com.aivisiondrone.groundstation.telemetry.DetectionsState
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * Draws every live object the AI currently sees (person, car, chair, ...),
 * not just the one being tracked - lets the operator see what's tappable
 * before picking a target. The actively-tracked box is drawn separately by
 * TrackingOverlay on top of this, in a different color, so it stands out.
 */
@Composable
fun DetectionsOverlay(detections: DetectionsState, modifier: Modifier = Modifier) {
    val srcWidth = detections.imageWidth
    val srcHeight = detections.imageHeight
    val labelPaint = remember {
        Paint().apply {
            color = Color.White.toArgb()
            textSize = 32f
            isAntiAlias = true
        }
    }

    Canvas(modifier = modifier.fillMaxSize()) {
        if (srcWidth == null || srcHeight == null || srcWidth <= 0 || srcHeight <= 0) return@Canvas
        val scaleX = size.width / srcWidth
        val scaleY = size.height / srcHeight

        for (det in detections.detections) {
            val topLeft = Offset((det.bbox.x * scaleX).toFloat(), (det.bbox.y * scaleY).toFloat())
            val boxSize = Size((det.bbox.w * scaleX).toFloat(), (det.bbox.h * scaleY).toFloat())
            
            // Minimal detection corners
            val color = DroneColors.Accent.copy(alpha = 0.6f)
            val stroke = 1.5f
            val cornerLen = 12f
            
            drawLine(color, topLeft, topLeft.copy(x = topLeft.x + cornerLen), stroke)
            drawLine(color, topLeft, topLeft.copy(y = topLeft.y + cornerLen), stroke)
            
            val topRight = topLeft.copy(x = topLeft.x + boxSize.width)
            drawLine(color, topRight, topRight.copy(x = topRight.x - cornerLen), stroke)
            drawLine(color, topRight, topRight.copy(y = topRight.y + cornerLen), stroke)
            
            val bottomLeft = topLeft.copy(y = topLeft.y + boxSize.height)
            drawLine(color, bottomLeft, bottomLeft.copy(x = bottomLeft.x + cornerLen), stroke)
            drawLine(color, bottomLeft, bottomLeft.copy(y = bottomLeft.y - cornerLen), stroke)
            
            val bottomRight = topLeft.copy(x = topLeft.x + boxSize.width, y = topLeft.y + boxSize.height)
            drawLine(color, bottomRight, bottomRight.copy(x = bottomRight.x - cornerLen), stroke)
            drawLine(color, bottomRight, bottomRight.copy(y = bottomRight.y - cornerLen), stroke)
            drawContext.canvas.nativeCanvas.drawText(
                "${det.className} ${(det.score * 100).toInt()}%",
                topLeft.x,
                (topLeft.y - 6f).coerceAtLeast(20f),
                labelPaint,
            )
        }
    }
}
