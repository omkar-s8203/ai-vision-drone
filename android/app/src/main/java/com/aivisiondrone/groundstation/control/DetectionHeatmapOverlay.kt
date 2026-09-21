package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp

/**
 * Renders a DetectionHeatmap snapshot as a translucent color overlay on the
 * live video - blue/cool where objects have rarely been detected recently,
 * red/hot where they've been detected often. Purely a visualization; it
 * never feeds back into tracking/guidance, which still only ever reasons
 * about the current frame's real detections. Opt-in (toggled from the Fly
 * tab HUD) since it's a nice-to-have overlay, not core operational UI, and
 * would otherwise clutter the live view by default.
 */
@Composable
fun DetectionHeatmapOverlay(snapshot: HeatmapSnapshot, modifier: Modifier = Modifier) {
    Canvas(modifier = modifier.fillMaxSize()) {
        val maxValue = snapshot.maxValue
        if (maxValue <= 0f || snapshot.cols <= 0 || snapshot.rows <= 0) return@Canvas

        val cellWidth = size.width / snapshot.cols
        val cellHeight = size.height / snapshot.rows

        for (row in 0 until snapshot.rows) {
            for (col in 0 until snapshot.cols) {
                val value = snapshot.cells[row * snapshot.cols + col]
                if (value <= 0f) continue
                val intensity = (value / maxValue).coerceIn(0f, 1f)
                drawRect(
                    color = heatColor(intensity),
                    topLeft = Offset(col * cellWidth, row * cellHeight),
                    size = Size(cellWidth, cellHeight),
                )
            }
        }
    }
}

// Cool-to-hot ramp: near-transparent blue (barely-there) through cyan and
// yellow to a mostly-opaque red (the busiest spot in frame right now) -
// the standard heatmap convention, so it reads correctly to anyone who's
// seen one before.
private val HEAT_STOPS = listOf(
    0.0f to Color(0x0042A5F5),
    0.35f to Color(0x6600E5FF),
    0.65f to Color(0x99FFEB3B),
    1.0f to Color(0xCCFF3D00),
)

private fun heatColor(intensity: Float): Color {
    for (i in 0 until HEAT_STOPS.size - 1) {
        val (t0, c0) = HEAT_STOPS[i]
        val (t1, c1) = HEAT_STOPS[i + 1]
        if (intensity <= t1) {
            val localT = if (t1 > t0) (intensity - t0) / (t1 - t0) else 0f
            return lerp(c0, c1, localT.coerceIn(0f, 1f))
        }
    }
    return HEAT_STOPS.last().second
}
