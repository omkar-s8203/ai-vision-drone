package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Autorenew
import androidx.compose.material.icons.filled.CenterFocusStrong
import androidx.compose.material.icons.filled.FlightTakeoff
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * DJI-style "target locked, now what?" quick action sheet - appears right
 * after a tap/drag selection locks tracking onto an object, letting the
 * operator immediately choose Track-only, Follow, Orbit (the "circle"
 * shot), or arm-and-follow in one action, without hunting through a
 * separate settings screen first.
 *
 * `armed` decides what the combined chip actually does: already armed, it
 * behaves exactly like the plain Follow chip (no point re-arming); not yet
 * armed, tapping it shows the same "motors will become live" confirmation
 * the Control tab's own Arm button already requires (FlightControlDock.kt)
 * before calling `onArmAndFollow` - a combined convenience action never
 * skips that confirmation, since arming is exactly as consequential here
 * as it is anywhere else in the app.
 */
@Composable
fun TargetActionSheet(
    armed: Boolean,
    onTrack: () -> Unit,
    onFollow: () -> Unit,
    onOrbit: () -> Unit,
    onArmAndFollow: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showArmConfirm by remember { mutableStateOf(false) }

    Card(
        modifier = modifier,
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 12.dp)
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                "Target Identified",
                color = DroneColors.TextPrimary,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold
            )
            androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(16.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                ActionChip(icon = Icons.Filled.CenterFocusStrong, label = "Track", onClick = onTrack)
                ActionChip(icon = Icons.Filled.Navigation, label = "Follow", onClick = onFollow)
                ActionChip(icon = Icons.Filled.Autorenew, label = "Orbit", onClick = onOrbit)
                // Only shown while disarmed - once armed, the plain "Follow"
                // chip above already does exactly this, so a second
                // identical-looking chip here would just be confusing.
                if (!armed) {
                    ActionChip(
                        icon = Icons.Filled.FlightTakeoff,
                        label = "Arm & Follow",
                        onClick = { showArmConfirm = true },
                    )
                }
            }
            androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(8.dp))
            TextButton(
                onClick = onCancel,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    "Dismiss",
                    color = DroneColors.TextSecondary,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Medium
                )
            }
        }
    }

    if (showArmConfirm) {
        AlertDialog(
            onDismissRequest = { showArmConfirm = false },
            icon = { Icon(Icons.Filled.Warning, contentDescription = null, tint = DroneColors.Warning) },
            title = { Text("Arm and follow this target?") },
            text = { Text("Motors will become live and the aircraft will start following immediately. Make sure the area is clear before arming.") },
            confirmButton = {
                TextButton(onClick = {
                    showArmConfirm = false
                    onArmAndFollow()
                }) { Text("ARM & FOLLOW", color = DroneColors.Danger) }
            },
            dismissButton = {
                TextButton(onClick = { showArmConfirm = false }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun ActionChip(icon: ImageVector, label: String, onClick: () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier
            .background(DroneColors.SurfaceElevated, RoundedCornerShape(16.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 14.dp),
    ) {
        Icon(icon, contentDescription = label, tint = DroneColors.Accent, modifier = Modifier.size(24.dp))
        Text(
            label,
            color = DroneColors.TextPrimary,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold
        )
    }
}
