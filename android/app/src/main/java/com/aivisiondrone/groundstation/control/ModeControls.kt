package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

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
    Column(modifier = modifier.padding(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DroneMode.entries.forEach { mode ->
                Button(
                    onClick = { onModeSelected(mode) },
                    colors = if (mode == currentMode) {
                        ButtonDefaults.buttonColors()
                    } else {
                        ButtonDefaults.outlinedButtonColors()
                    },
                ) {
                    Text(mode.label)
                }
            }
        }
        if (currentMode == DroneMode.FOLLOWING) {
            Text("Follow distance: ${"%.1f".format(followSeparationM)} m")
            Slider(
                value = followSeparationM,
                onValueChange = onFollowSeparationChanged,
                valueRange = 3f..15f,
            )
            Text("Follow altitude: ${"%.1f".format(followAltitudeM)} m")
            Slider(
                value = followAltitudeM,
                onValueChange = onFollowAltitudeChanged,
                valueRange = 2f..30f,
            )
        }
    }
}
