package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FlightTakeoff
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** ArduCopter modes relevant to a companion-computer ground station - mirrors
 * companion/mavlink/bridge.py's ARDUCOPTER_MODE_TO_NUMBER keys, kept in sync
 * by hand since this list is intentionally a curated subset (not every
 * ArduCopter mode makes sense to expose to this operator). */
val SELECTABLE_FLIGHT_MODES = listOf(
    "STABILIZE", "ALT_HOLD", "LOITER", "POSHOLD", "GUIDED", "AUTO", "RTL", "LAND", "BRAKE",
)

/**
 * Flight-control dock: arm/disarm and flight mode selection - the
 * administrative FC commands, layered on top of the AI mode controls
 * (Idle/Tracking/Follow/Approach), which stay separate since they mean
 * something different (AI guidance state, not FC state). Video recording
 * lives on the main Fly screen instead (RecordButton.kt), not here.
 *
 * Deliberately a full-width vertical stack rather than a side-by-side row:
 * a fixed-width row of a button plus a dropdown clips or squeezes text
 * illegibly on narrow/low-density screens (confirmed on a real
 * remote-controller-mounted display) - stacking removes that failure mode
 * entirely regardless of screen width.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FlightControlDock(
    armed: Boolean,
    flightMode: String?,
    onArmChanged: (Boolean) -> Unit,
    onForceDisarm: () -> Unit,
    onFlightModeSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var showArmConfirm by remember { mutableStateOf(false) }
    var showForceDisarmConfirm by remember { mutableStateOf(false) }
    var modeMenuExpanded by remember { mutableStateOf(false) }

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Button(
                onClick = { if (armed) onArmChanged(false) else showArmConfirm = true },
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (armed) DroneColors.Danger else DroneColors.Accent,
                    contentColor = if (armed) Color.White else Color.Black,
                ),
                modifier = Modifier.fillMaxWidth().height(50.dp),
            ) {
                Icon(
                    Icons.Filled.FlightTakeoff, 
                    contentDescription = null, 
                    modifier = Modifier.size(20.dp),
                    tint = if (armed) Color.White else Color.Black
                )
                Text(
                    text = if (armed) "DISARM" else "ARM",
                    fontWeight = FontWeight.Black,
                    modifier = Modifier.padding(start = 8.dp)
                )
            }

            // A real field-reported gap: ArduCopter refuses a normal
            // (unforced) disarm outright if its own land-detector believes
            // the aircraft is flying - a bench test with props spinning can
            // trip that as a false positive, and the DISARM button above
            // then does nothing with no visible error (this bridge doesn't
            // listen for COMMAND_ACK). This sends the command's own
            // documented "force" override for exactly that case - kept as
            // a separate, less prominent control with its own stronger
            // confirmation, not folded into the main button, since it
            // bypasses a real in-flight safety protection and should never
            // be reached for by accident.
            if (armed) {
                TextButton(
                    onClick = { showForceDisarmConfirm = true },
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                ) {
                    Text(
                        "Force disarm (if DISARM doesn't respond)",
                        color = DroneColors.Warning,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }

            ExposedDropdownMenuBox(
                expanded = modeMenuExpanded,
                onExpandedChange = { modeMenuExpanded = it },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 16.dp),
            ) {
                TextField(
                    value = flightMode ?: "--",
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("FC Mode") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = modeMenuExpanded) },
                    modifier = Modifier
                        .menuAnchor()
                        .fillMaxWidth(),
                    colors = TextFieldDefaults.colors(
                        focusedContainerColor = Color.Transparent,
                        unfocusedContainerColor = Color.Transparent,
                        focusedIndicatorColor = Color.Transparent,
                        unfocusedIndicatorColor = Color.Transparent,
                        focusedTextColor = DroneColors.TextPrimary,
                        unfocusedTextColor = DroneColors.TextPrimary,
                        focusedLabelColor = DroneColors.Accent,
                        unfocusedLabelColor = DroneColors.TextSecondary
                    ),
                )
                ExposedDropdownMenu(
                    expanded = modeMenuExpanded,
                    onDismissRequest = { modeMenuExpanded = false },
                    modifier = Modifier.background(DroneColors.Surface)
                ) {
                    SELECTABLE_FLIGHT_MODES.forEach { candidate ->
                        DropdownMenuItem(
                            text = { 
                                Text(
                                    candidate,
                                    color = DroneColors.TextPrimary,
                                    fontWeight = if (candidate == flightMode) FontWeight.Bold else FontWeight.Normal
                                ) 
                            },
                            onClick = {
                                modeMenuExpanded = false
                                onFlightModeSelected(candidate)
                            },
                        )
                    }
                }
            }
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

    if (showForceDisarmConfirm) {
        AlertDialog(
            onDismissRequest = { showForceDisarmConfirm = false },
            icon = { Icon(Icons.Filled.Warning, contentDescription = null, tint = DroneColors.Danger) },
            title = { Text("Force disarm?") },
            text = {
                Text(
                    "Only use this if the normal DISARM button did nothing " +
                        "and you are certain the aircraft is on the ground. " +
                        "This overrides the flight controller's own " +
                        "protection against disarming while it thinks it's flying."
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showForceDisarmConfirm = false
                    onForceDisarm()
                }) { Text("FORCE DISARM", color = DroneColors.Danger) }
            },
            dismissButton = {
                TextButton(onClick = { showForceDisarmConfirm = false }) { Text("Cancel") }
            },
        )
    }
}
