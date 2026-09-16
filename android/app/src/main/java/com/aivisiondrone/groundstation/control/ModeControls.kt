package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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

enum class DroneMode(val wireValue: String, val label: String) {
    IDLE("idle", "Normal RC"),
    TRACKING("tracking", "Tracking"),
    FOLLOWING("follow", "Follow"),
    APPROACHING("approach", "Approach Test"),
}

@Composable
fun ModeControls(
    currentMode: DroneMode,
    followSeparationM: Float,
    followAltitudeM: Float,
    onModeSelected: (DroneMode) -> Unit,
    onFollowSeparationChanged: (Float) -> Unit,
    onFollowAltitudeChanged: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.92f)),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
                Text(
                    "Follow distance: ${"%.1f".format(followSeparationM)} m",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.labelMedium,
                )
                Slider(
                    value = followSeparationM,
                    onValueChange = onFollowSeparationChanged,
                    valueRange = 3f..15f,
                    colors = SliderDefaults.colors(thumbColor = DroneColors.Accent, activeTrackColor = DroneColors.Accent),
                )
                Text(
                    "Follow altitude: ${"%.1f".format(followAltitudeM)} m",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.labelMedium,
                )
                Slider(
                    value = followAltitudeM,
                    onValueChange = onFollowAltitudeChanged,
                    valueRange = 2f..30f,
                    colors = SliderDefaults.colors(thumbColor = DroneColors.Accent, activeTrackColor = DroneColors.Accent),
                )
            }
        }
    }
}
