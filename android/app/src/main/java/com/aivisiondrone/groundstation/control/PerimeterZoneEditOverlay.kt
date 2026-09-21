package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
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
 * Drag-to-define overlay for the perimeter/intrusion zone (a defence-
 * relevant field request: "perimeter / intrusion alert") - shown instead
 * of TargetSelectionOverlay while the operator is actively setting the
 * zone (mutually exclusive, toggled from FlyTab's "PERIMETER" HUD chip),
 * so the two drag gestures never conflict. Reports the drawn rectangle in
 * the overlay's own pixel space; the caller scales it to the source video
 * resolution before storing it, the same pattern TargetSelectionOverlay
 * already uses for target_select.
 */
@Composable
fun PerimeterZoneEditOverlay(modifier: Modifier = Modifier, onZoneDefined: (Rect) -> Unit) {
    var dragStart by remember { mutableStateOf<Offset?>(null) }
    var dragCurrent by remember { mutableStateOf<Offset?>(null) }

    Canvas(
        modifier = modifier
            .fillMaxSize()
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
                                onZoneDefined(rect)
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
                color = Color(0xFFFF6D00), // distinct orange, not the yellow target-selection uses
                topLeft = topLeft,
                size = size,
                style = Stroke(width = 4f),
            )
        }
    }
}
