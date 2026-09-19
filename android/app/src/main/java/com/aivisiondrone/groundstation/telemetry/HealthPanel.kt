package com.aivisiondrone.groundstation.telemetry

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

@Composable
fun HealthPanel(health: HealthState, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .background(DroneColors.SurfaceElevated, RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
    ) {
        HealthIndicator("SYS", health.piOk)
        HealthIndicator("CAM", health.cameraOk)
        HealthIndicator("AI", health.aiOk)
        HealthIndicator("LINK", health.mavlinkOk)
        
        Box(modifier = Modifier.width(1.dp).height(14.dp).background(DroneColors.Surface))
        
        Text(
            "${health.fps?.let { "%.0f".format(it) } ?: "--"} FPS",
            color = DroneColors.TextSecondary,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}

@Composable
private fun HealthIndicator(label: String, ok: Boolean) {
    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Box(
            modifier = Modifier
                .size(6.dp)
                .background(if (ok) DroneColors.Safe else DroneColors.Danger, androidx.compose.foundation.shape.CircleShape)
        )
        Text(
            text = label,
            color = if (ok) DroneColors.TextPrimary else DroneColors.TextSecondary,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold
        )
    }
}
