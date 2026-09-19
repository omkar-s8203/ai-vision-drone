package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** AI guidance mode - distinct from the FC's own flight mode (STABILIZE,
 * LOITER, etc. - see FlightControlDock). ORBITING is the DJI "circle"/
 * point-of-interest equivalent: the drone holds a radius around the
 * selected target and sweeps around it instead of holding station. DRONIE
 * and PARABOLA are one-shot cinematic moves (DJI "QuickShot" equivalent) -
 * unlike the other modes they run once for a fixed duration and then stop
 * themselves on the Pi side (companion/guidance/smart_shot.py); tapping
 * the button again just re-triggers a fresh run. */
enum class DroneMode(val wireValue: String, val label: String) {
    IDLE("idle", "Normal RC"),
    TRACKING("tracking", "Tracking"),
    FOLLOWING("follow", "Follow"),
    ORBITING("orbit", "Orbit"),
    APPROACHING("approach", "Approach Test"),
    DRONIE("dronie", "Dronie"),
    PARABOLA("parabola", "Parabola"),
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
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                "AI GUIDANCE MODE",
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(bottom = 12.dp)
            )
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                DroneMode.entries.forEach { mode ->
                    Button(
                        onClick = { onModeSelected(mode) },
                        shape = RoundedCornerShape(12.dp),
                        colors = if (mode == currentMode) {
                            ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = Color.White)
                        } else {
                            ButtonDefaults.buttonColors(containerColor = DroneColors.SurfaceElevated, contentColor = DroneColors.TextPrimary)
                        },
                        modifier = Modifier.height(40.dp)
                    ) {
                        Text(mode.label, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            if (currentMode == DroneMode.FOLLOWING || currentMode == DroneMode.ORBITING) {
                Spacer(modifier = Modifier.height(20.dp))
                androidx.compose.material3.HorizontalDivider(
                    thickness = 0.5.dp,
                    color = DroneColors.SurfaceElevated
                )
                Spacer(modifier = Modifier.height(16.dp))
            }

            if (currentMode == DroneMode.FOLLOWING) {
                LabeledSlider(
                    label = "Follow distance",
                    valueText = "${"%.1f".format(followSeparationM)} m",
                    value = followSeparationM,
                    onValueChange = onFollowSeparationChanged,
                    valueRange = 3f..15f,
                )
                Spacer(modifier = Modifier.height(12.dp))
                LabeledSlider(
                    label = "Follow altitude",
                    valueText = "${"%.1f".format(followAltitudeM)} m",
                    value = followAltitudeM,
                    onValueChange = onFollowAltitudeChanged,
                    valueRange = 2f..30f,
                )
            }
            if (currentMode == DroneMode.ORBITING) {
                LabeledSlider(
                    label = "Orbit radius",
                    valueText = "${"%.1f".format(orbitRadiusM)} m",
                    value = orbitRadiusM,
                    onValueChange = onOrbitRadiusChanged,
                    valueRange = 3f..20f,
                )
                Spacer(modifier = Modifier.height(12.dp))
                LabeledSlider(
                    label = "Orbit altitude",
                    valueText = "${"%.1f".format(orbitAltitudeM)} m",
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
    valueText: String,
    value: Float,
    onValueChange: (Float) -> Unit,
    valueRange: ClosedFloatingPointRange<Float>,
) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(label, color = DroneColors.TextPrimary, style = MaterialTheme.typography.bodyMedium)
            Text(valueText, color = DroneColors.Accent, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
        }
        Slider(
            value = value,
            onValueChange = onValueChange,
            valueRange = valueRange,
            colors = SliderDefaults.colors(
                thumbColor = Color.White,
                activeTrackColor = DroneColors.Accent,
                inactiveTrackColor = DroneColors.SurfaceElevated
            ),
        )
    }
}
