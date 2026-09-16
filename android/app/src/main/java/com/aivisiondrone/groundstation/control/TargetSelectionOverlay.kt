package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput

/**
 * Target selection overlay on top of the live video surface: a quick tap
 * selects whichever detected object is under it (matched against the Pi's
 * current detections - see DetectionsOverlay), while a drag draws an
 * explicit selection rectangle for anything not already recognized as its
 * own detection. Reports coordinates in the overlay's own pixel space; the
 * caller (MainViewModel) scales them to the source video resolution before
 * sending target_select to the Pi (docs plan M6/M3).
 */
@Composable
fun TargetSelectionOverlay(
    modifier: Modifier = Modifier,
    onTapSelect: (Offset) -> Unit,
    onSelectionComplete: (Rect) -> Unit,
) {
    var dragStart by remember { mutableStateOf<Offset?>(null) }
    var dragCurrent by remember { mutableStateOf<Offset?>(null) }

    Canvas(
        modifier = modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                detectTapGestures(onTap = { offset -> onTapSelect(offset) })
            }
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { offset ->
                        dragStart = offset
                        dragCurrent = offset
                    },
                    onDrag = { change, _ ->
                        dragCurrent = change.position
                    },
                    onDragEnd = {
                        val start = dragStart
                        val end = dragCurrent
                        if (start != null && end != null) {
                            val rect = Rect(
                                left = minOf(start.x, end.x),
                                top = minOf(start.y, end.y),
                                right = maxOf(start.x, end.x),
                                bottom = maxOf(start.y, end.y),
                            )
                            if (rect.width > 8f && rect.height > 8f) {
                                onSelectionComplete(rect)
                            }
                        }
                        dragStart = null
                        dragCurrent = null
                    },
                )
            },
    ) {
        val start = dragStart
        val current = dragCurrent
        if (start != null && current != null) {
            val topLeft = Offset(minOf(start.x, current.x), minOf(start.y, current.y))
            val size = Size(kotlin.math.abs(current.x - start.x), kotlin.math.abs(current.y - start.y))
            drawRect(
                color = Color.Yellow,
                topLeft = topLeft,
                size = size,
                style = Stroke(width = 4f),
            )
        }
    }
}
