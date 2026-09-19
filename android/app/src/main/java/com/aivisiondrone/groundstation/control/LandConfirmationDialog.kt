package com.aivisiondrone.groundstation.control

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import com.aivisiondrone.groundstation.telemetry.LandConfirmationRequest
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * Target-loss recovery's search timed out and battery/distance say landing
 * in place is safer than RTL (companion/guidance/target_recovery.py) -
 * this is the operator decision that gates it. Landing NEVER happens
 * automatically; onApprove/onDeny are the only two ways this resolves.
 * obstacleDetected is shown as information the operator should weigh, not
 * something this dialog decides on its own.
 */
@Composable
fun LandConfirmationDialog(
    request: LandConfirmationRequest,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDeny,  // dismissing (e.g. back button) is a denial, not a silent no-op
        icon = { Icon(Icons.Filled.Warning, contentDescription = null, tint = DroneColors.Danger) },
        title = { Text("Land now?") },
        text = {
            Text(
                "Target lost and not found after searching. " +
                    (request.batteryRemainingPct?.let { "Battery: $it%. " } ?: "") +
                    (request.distanceToHomeM?.let { "Distance to home: %.0f m. ".format(it) } ?: "") +
                    "RTL may not be reliable from here.\n\n" +
                    if (request.obstacleDetected) {
                        "Warning: the AI currently sees ${request.obstacleClassName ?: "an object"} " +
                            "nearby - check the video feed before approving."
                    } else {
                        "No obstacle currently detected by the AI, but confirm the landing area " +
                            "looks clear on the video feed before approving."
                    },
            )
        },
        confirmButton = {
            TextButton(onClick = onApprove) { Text("LAND", color = DroneColors.Danger) }
        },
        dismissButton = {
            TextButton(onClick = onDeny) { Text("Don't land") }
        },
    )
}
