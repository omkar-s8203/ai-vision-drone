package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** AI guidance mode - distinct from the FC's own flight mode (STABILIZE,
 * LOITER, etc. - see FlightControlDock). ORBITING is the DJI "circle"/
 * point-of-interest equivalent: the drone holds a radius around the
 * selected target and sweeps around it instead of holding station. */
enum class DroneMode(val wireValue: String, val label: String) {
    IDLE("idle", "Normal RC"),
    TRACKING("tracking", "Tracking"),
    FOLLOWING("follow", "Follow"),
    ORBITING("orbit", "Orbit"),
    APPROACHING("approach", "Approach Test"),
}

@Composable
fun ModeControls(
    currentMode: DroneMode,
    followSeparationM: Float,
    followAltitudeM: Float,
    orbitRadiusM: Float,
    orbitAltitudeM: Float,
    onModeSelected: (DroneMode) -> Unit,
    onFollowSeparationChanged: (Float) -> Unit,
    onFollowAltitudeChanged: (Float) -> Unit,
    onOrbitRadiusChanged: (Float) -> Unit,
    onOrbitAltitudeChanged: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.92f)),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                DroneMode.entries.forEach { mode ->
                    Button(
                        onClick = { onModeSelected(mode) },
                        colors = if (mode == currentMode) {
                            ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = Color(0xFF00232A))
                        } else {
                            ButtonDefaults.outlinedButtonColors(contentColor = DroneColors.TextPrimary)
                        },
                    ) {
                        Text(mode.label)
                    }
                }
            }
            if (currentMode == DroneMode.FOLLOWING) {
                LabeledSlider(
                    label = "Follow distance: ${"%.1f".format(followSeparationM)} m",
                    value = followSeparationM,
                    onValueChange = onFollowSeparationChanged,
                    valueRange = 3f..15f,
                )
                LabeledSlider(
                    label = "Follow altitude: ${"%.1f".format(followAltitudeM)} m",
                    value = followAltitudeM,
                    onValueChange = onFollowAltitudeChanged,
                    valueRange = 2f..30f,
                )
            }
            if (currentMode == DroneMode.ORBITING) {
                LabeledSlider(
                    label = "Orbit radius: ${"%.1f".format(orbitRadiusM)} m",
                    value = orbitRadiusM,
                    onValueChange = onOrbitRadiusChanged,
                    valueRange = 3f..20f,
                )
                LabeledSlider(
                    label = "Orbit altitude: ${"%.1f".format(orbitAltitudeM)} m",
                    value = orbitAltitudeM,
                    onValueChange = onOrbitAltitudeChanged,
                    valueRange = 2f..30f,
                )
            }
        }
    }
}

@Composable
private fun LabeledSlider(
    label: String,
    value: Float,
    onValueChange: (Float) -> Unit,
    valueRange: ClosedFloatingPointRange<Float>,
) {
    Text(label, color = DroneColors.TextSecondary, style = MaterialTheme.typography.labelMedium)
    Slider(
        value = value,
        onValueChange = onValueChange,
        valueRange = valueRange,
        colors = SliderDefaults.colors(thumbColor = DroneColors.Accent, activeTrackColor = DroneColors.Accent),
    )
}
