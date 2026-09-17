package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Autorenew
import androidx.compose.material.icons.filled.CenterFocusStrong
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * DJI-style "target locked, now what?" quick action sheet - appears right
 * after a tap/drag selection locks tracking onto an object, letting the
 * operator immediately choose Track-only, Follow, or Orbit (the "circle"
 * shot) without hunting through a separate settings screen first.
 */
@Composable
fun TargetActionSheet(
    onTrack: () -> Unit,
    onFollow: () -> Unit,
    onOrbit: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.96f)),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                "Target locked - choose an action",
                color = DroneColors.TextPrimary,
                style = MaterialTheme.typography.labelLarge,
            )
            Row(
                modifier = Modifier.padding(top = 10.dp, bottom = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                ActionChip(icon = Icons.Filled.CenterFocusStrong, label = "Track", onClick = onTrack)
                ActionChip(icon = Icons.Filled.Navigation, label = "Follow", onClick = onFollow)
                ActionChip(icon = Icons.Filled.Autorenew, label = "Orbit", onClick = onOrbit)
            }
            TextButton(onClick = onCancel) {
                Text("Cancel", color = DroneColors.TextSecondary)
            }
        }
    }
}

@Composable
private fun ActionChip(icon: ImageVector, label: String, onClick: () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .background(DroneColors.SurfaceElevated, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
    ) {
        Icon(icon, contentDescription = label, tint = DroneColors.Accent)
        Text(label, color = DroneColors.TextPrimary, style = MaterialTheme.typography.labelSmall)
    }
}
