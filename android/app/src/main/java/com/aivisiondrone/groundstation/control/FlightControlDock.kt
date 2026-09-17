package com.aivisiondrone.groundstation.control

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.FlightTakeoff
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** ArduCopter modes relevant to a companion-computer ground station - mirrors
 * companion/mavlink/bridge.py's ARDUCOPTER_MODE_TO_NUMBER keys, kept in sync
 * by hand since this list is intentionally a curated subset (not every
 * ArduCopter mode makes sense to expose to this operator). */
val SELECTABLE_FLIGHT_MODES = listOf(
    "STABILIZE", "ALT_HOLD", "LOITER", "POSHOLD", "GUIDED", "AUTO", "RTL", "LAND", "BRAKE",
)

private fun formatDuration(seconds: Double): String {
    val total = seconds.toInt().coerceAtLeast(0)
    val m = total / 60
    val s = total % 60
    return "%d:%02d".format(m, s)
}

/**
 * Bottom flight-control dock: arm/disarm, flight mode selection, and video
 * recording - the "professional GCS" commands layered on top of the
 * existing AI mode controls (Idle/Tracking/Follow/Approach), which stay
 * separate since they mean something different (AI guidance state, not FC
 * state).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FlightControlDock(
    armed: Boolean,
    flightMode: String?,
    recording: Boolean,
    recordingDurationS: Double,
    onArmChanged: (Boolean) -> Unit,
    onFlightModeSelected: (String) -> Unit,
    onToggleRecording: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showArmConfirm by remember { mutableStateOf(false) }
    var modeMenuExpanded by remember { mutableStateOf(false) }

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.92f)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ArmDisarmButton(
                armed = armed,
                onClick = {
                    if (armed) onArmChanged(false) else showArmConfirm = true
                },
                modifier = Modifier.weight(1f),
            )

            ExposedDropdownMenuBox(
                expanded = modeMenuExpanded,
                onExpandedChange = { modeMenuExpanded = it },
                modifier = Modifier.weight(1.3f),
            ) {
                OutlinedTextField(
                    value = flightMode ?: "--",
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("FC Mode") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = modeMenuExpanded) },
                    modifier = Modifier
                        .menuAnchor()
                        .fillMaxWidth(),
                )
                ExposedDropdownMenu(
                    expanded = modeMenuExpanded,
                    onDismissRequest = { modeMenuExpanded = false },
                ) {
                    SELECTABLE_FLIGHT_MODES.forEach { candidate ->
                        DropdownMenuItem(
                            text = { Text(candidate) },
                            onClick = {
                                modeMenuExpanded = false
                                onFlightModeSelected(candidate)
                            },
                        )
                    }
                }
            }

            RecordButton(
                recording = recording,
                durationS = recordingDurationS,
                onClick = onToggleRecording,
            )
        }
    }

    if (showArmConfirm) {
        AlertDialog(
            onDismissRequest = { showArmConfirm = false },
            icon = { Icon(Icons.Filled.Warning, contentDescription = null, tint = DroneColors.Warning) },
            title = { Text("Arm the aircraft?") },
            text = { Text("Motors will become live. Make sure the area is clear before arming.") },
            confirmButton = {
                TextButton(onClick = {
                    showArmConfirm = false
                    onArmChanged(true)
                }) { Text("ARM", color = DroneColors.Danger) }
            },
            dismissButton = {
                TextButton(onClick = { showArmConfirm = false }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun RowScope.ArmDisarmButton(armed: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Button(
        onClick = onClick,
        colors = ButtonDefaults.buttonColors(
            containerColor = if (armed) DroneColors.Danger else DroneColors.SurfaceElevated,
            contentColor = Color.White,
        ),
        modifier = modifier,
    ) {
        Icon(Icons.Filled.FlightTakeoff, contentDescription = null, modifier = Modifier.size(18.dp))
        Text(
            text = if (armed) "DISARM" else "ARM",
            modifier = Modifier.padding(start = 6.dp),
        )
    }
}

@Composable
private fun RecordButton(recording: Boolean, durationS: Double, onClick: () -> Unit) {
    val transition = rememberInfiniteTransition(label = "record-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label = "record-pulse-alpha",
    )

    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        IconButton(
            onClick = onClick,
            modifier = Modifier
                .size(44.dp)
                .background(DroneColors.SurfaceElevated, CircleShape),
        ) {
            Icon(
                imageVector = if (recording) Icons.Filled.Stop else Icons.Filled.FiberManualRecord,
                contentDescription = if (recording) "Stop recording" else "Start recording",
                tint = if (recording) DroneColors.Danger.copy(alpha = pulse) else DroneColors.TextPrimary,
            )
        }
        if (recording) {
            Text(
                text = formatDuration(durationS),
                color = DroneColors.Danger,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
