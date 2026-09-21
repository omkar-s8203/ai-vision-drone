package com.aivisiondrone.groundstation.control

import com.aivisiondrone.groundstation.telemetry.DetectionsState

private const val HEATMAP_COLS = 32
private const val HEATMAP_ROWS = 18

// Half-life of roughly 30s at a typical ~20-30Hz detections_update rate:
// solve DECAY^n = 0.5 for n around 600-900 updates. Deliberately a decay,
// not a permanent running total - a heatmap that only ever accumulates
// would saturate to solid red everywhere after a long session and stop
// meaning anything. This favors recent activity instead, so it reads as
// "where things have been happening lately."
private const val DECAY_PER_UPDATE = 0.999f

/** Immutable snapshot of the heatmap grid - safe to expose via StateFlow
 * and read from Compose without any risk of it mutating mid-recomposition
 * (the mutable FloatArray backing DetectionHeatmap itself never is). */
data class HeatmapSnapshot(val cols: Int, val rows: Int, val cells: FloatArray) {
    val maxValue: Float get() = cells.maxOrNull() ?: 0f

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is HeatmapSnapshot) return false
        return cols == other.cols && rows == other.rows && cells.contentEquals(other.cells)
    }

    override fun hashCode(): Int {
        var result = cols
        result = 31 * result + rows
        result = 31 * result + cells.contentHashCode()
        return result
    }

    companion object {
        val EMPTY = HeatmapSnapshot(HEATMAP_COLS, HEATMAP_ROWS, FloatArray(HEATMAP_COLS * HEATMAP_ROWS))
    }
}

/**
 * Accumulates a detection-density heatmap from the live `detections_update`
 * stream (docs/protocol.md) - not a thermal/IR camera feature (this is a
 * plain RGB camera), but a "where has the AI been seeing things" overlay:
 * every detection's bbox center bumps up the heat of the grid cell it
 * falls in, and every cell decays a little on every update (whether or not
 * that update had any detections) so the map reflects recent activity with
 * a fading trail, not one number that only ever goes up.
 *
 * Deliberately plain Kotlin, no Compose dependency - MainViewModel owns
 * one, updates it as DETECTIONS_UPDATE messages arrive, and exposes
 * immutable HeatmapSnapshot copies via StateFlow for the UI to render
 * (DetectionHeatmapOverlay.kt).
 */
class DetectionHeatmap(private val cols: Int = HEATMAP_COLS, private val rows: Int = HEATMAP_ROWS) {
    private val cells = FloatArray(cols * rows)

    fun record(detections: DetectionsState) {
        for (i in cells.indices) cells[i] *= DECAY_PER_UPDATE

        val width = detections.imageWidth
        val height = detections.imageHeight
        if (width == null || height == null || width <= 0 || height <= 0) return

        for (det in detections.detections) {
            val cx = det.bbox.x + det.bbox.w / 2.0
            val cy = det.bbox.y + det.bbox.h / 2.0
            val col = ((cx / width) * cols).toInt().coerceIn(0, cols - 1)
            val row = ((cy / height) * rows).toInt().coerceIn(0, rows - 1)
            cells[row * cols + col] += 1f
        }
    }

    fun snapshot(): HeatmapSnapshot = HeatmapSnapshot(cols, rows, cells.copyOf())

    fun clear() {
        cells.fill(0f)
    }
}
