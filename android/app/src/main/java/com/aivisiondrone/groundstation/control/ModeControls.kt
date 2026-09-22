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
    // Has a real button in the row below like every other mode, but a tap
    // never fires onModeSelected -> setMode() straight to the wire the way
    // every other button does - unlike them, starting this one needs
    // width/height parameters first (see GridSearchControls.kt), so a bare
    // {"mode": "grid_search"} with no area dimensions would just bounce
    // back to idle on the Pi (companion/main.py's _on_mode_command). See
    // AiModesTab.kt: this button only opens/closes the config panel
    // locally; the real mode_command is sent once "Start Grid Search" is
    // tapped inside it. A field request extending the existing
    // single-target search into deliberate area coverage, the same
    // recon/surveillance use case as the Android app's perimeter/intrusion
    // alert.
    GRID_SEARCH("grid_search", "Grid Search"),
}

// Mirrors follow_limits.yaml/orbit_limits.yaml's min_speed_mps/max_speed_mps -
// the slider's own range must match the server-side floor/ceiling
// (FollowController/OrbitController.set_max_speed both clamp to this same
// range regardless of what the slider sends, but a mismatched UI range
// would be misleading about what's actually achievable).
private const val MIN_SPEED_MPS = 0.5f
private const val MAX_SPEED_MPS = 3.0f

@Composable
fun ModeControls(
    currentMode: DroneMode,
    followSeparationM: Float,
    followAltitudeM: Float,
    orbitRadiusM: Float,
    orbitAltitudeM: Float,
    followMaxSpeedMps: Float,
    orbitMaxSpeedMps: Float,
    onModeSelected: (DroneMode) -> Unit,
    onFollowSeparationChanged: (Float) -> Unit,
    onFollowAltitudeChanged: (Float) -> Unit,
    onOrbitRadiusChanged: (Float) -> Unit,
    onOrbitAltitudeChanged: (Float) -> Unit,
    onFollowMaxSpeedChanged: (Float) -> Unit,
    onOrbitMaxSpeedChanged: (Float) -> Unit,
    // True while the Grid Search config panel is open/the sweep is
    // running - GRID_SEARCH's own button highlights for both, even though
    // `currentMode` itself only actually becomes GRID_SEARCH once a sweep
    // is started (see the enum's own docstring for why a tap doesn't just
    // call onModeSelected the way every other button's does).
    gridSearchSelected: Boolean = false,
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
                    val selected = mode == currentMode || (mode == DroneMode.GRID_SEARCH && gridSearchSelected)
                    Button(
                        onClick = { onModeSelected(mode) },
                        shape = RoundedCornerShape(12.dp),
                        colors = if (selected) {
                            ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = Color.Black)
                        } else {
                            ButtonDefaults.buttonColors(containerColor = DroneColors.SurfaceElevated, contentColor = DroneColors.TextPrimary)
                        },
                        modifier = Modifier.height(40.dp)
                    ) {
                        Text(mode.label, fontWeight = FontWeight.Black)
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
                Spacer(modifier = Modifier.height(12.dp))
                LabeledSlider(
                    label = "Speed",
                    valueText = "${"%.1f".format(followMaxSpeedMps)} m/s",
                    value = followMaxSpeedMps,
                    onValueChange = onFollowMaxSpeedChanged,
                    valueRange = MIN_SPEED_MPS..MAX_SPEED_MPS,
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
                Spacer(modifier = Modifier.height(12.dp))
                LabeledSlider(
                    label = "Speed",
                    valueText = "${"%.1f".format(orbitMaxSpeedMps)} m/s",
                    value = orbitMaxSpeedMps,
                    onValueChange = onOrbitMaxSpeedChanged,
                    valueRange = MIN_SPEED_MPS..MAX_SPEED_MPS,
                )
            }
        }
    }
}

/** Not private: reused by GridSearchControls.kt in this same package. */
@Composable
fun LabeledSlider(
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
