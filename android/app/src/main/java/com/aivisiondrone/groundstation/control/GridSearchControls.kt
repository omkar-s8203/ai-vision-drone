package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.telemetry.GridSearchState
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * Systematic area-sweep ("lawnmower") search mode controls - a field
 * request extending the existing single-target search into deliberate
 * area coverage, the same recon/surveillance use case as the Fly tab's
 * perimeter/intrusion alert. Kept as its own card rather than folded into
 * ModeControls' button row: unlike every other mode, starting this one
 * needs width/height parameters up front, and once running those
 * parameters aren't live-adjustable (the sweep is already planned) - so
 * this shows a start form OR live progress, never both.
 *
 * The area's start corner is the aircraft's own current position at the
 * moment `onStart` is called (companion/main.py reads it directly from
 * live telemetry when it handles the mode_command) - fly to one corner of
 * the area to search, then start the sweep from there, rather than an
 * interactive map-drawing UI.
 */
@Composable
fun GridSearchControls(
    gridSearchState: GridSearchState,
    hasGpsFix: Boolean,
    onStart: (widthM: Float, heightM: Float) -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var widthM by remember { mutableFloatStateOf(60f) }
    var heightM by remember { mutableFloatStateOf(40f) }

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                "GRID SEARCH",
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(bottom = 12.dp)
            )

            if (gridSearchState.active) {
                val total = gridSearchState.waypoints.size
                val current = (gridSearchState.currentIndex + 1).coerceAtMost(total)
                Text(
                    "Sweeping - leg $current of $total",
                    color = DroneColors.TextPrimary,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(modifier = Modifier.padding(top = 12.dp))
                Button(
                    onClick = onStop,
                    colors = ButtonDefaults.buttonColors(containerColor = DroneColors.Danger, contentColor = Color.White),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Stop Sweep")
                }
            } else {
                LabeledSlider(
                    label = "Area width",
                    valueText = "${widthM.toInt()} m",
                    value = widthM,
                    onValueChange = { widthM = it },
                    valueRange = 20f..200f,
                )
                Spacer(modifier = Modifier.padding(top = 12.dp))
                LabeledSlider(
                    label = "Area height",
                    valueText = "${heightM.toInt()} m",
                    value = heightM,
                    onValueChange = { heightM = it },
                    valueRange = 20f..200f,
                )
                Spacer(modifier = Modifier.padding(top = 8.dp))
                Text(
                    "Starts from the aircraft's current position as one corner of the area.",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.bodySmall,
                )
                // Preventive, not just reactive: without a GPS fix the Pi
                // silently refuses to start (falls back to idle - see
                // companion/main.py's _on_mode_command) with nothing on
                // this screen to explain why the button appeared to do
                // nothing. Disabling it up front and saying why is a
                // clearer signal than a mysterious no-op.
                if (!hasGpsFix) {
                    Spacer(modifier = Modifier.padding(top = 8.dp))
                    Text(
                        "GPS fix required to start a grid search.",
                        color = DroneColors.Warning,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Spacer(modifier = Modifier.padding(top = 12.dp))
                Button(
                    onClick = { onStart(widthM, heightM) },
                    enabled = hasGpsFix,
                    colors = ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = Color.Black),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Start Grid Search")
                }
            }
        }
    }
}
