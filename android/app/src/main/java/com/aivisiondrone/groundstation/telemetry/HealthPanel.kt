package com.aivisiondrone.groundstation.telemetry

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
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
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Overlay),
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                HealthDot("PI", health.piOk)
                HealthDot("CAM", health.cameraOk)
                HealthDot("AI", health.aiOk)
                HealthDot("TRK", health.trackerOk)
                HealthDot("MAV", health.mavlinkOk)
                HealthDot("VID", health.videoOk)
            }
            Text(
                "FPS: ${health.fps?.let { "%.0f".format(it) } ?: "--"}   " +
                    "Latency: ${health.latencyMs?.let { "%.0f ms".format(it) } ?: "--"}   " +
                    "Temp: ${health.temperatureC?.let { "%.0f C".format(it) } ?: "--"}",
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
private fun HealthDot(label: String, ok: Boolean) {
    Text(
        text = "$label ${if (ok) "OK" else "--"}",
        color = if (ok) DroneColors.Safe else DroneColors.Danger,
        style = MaterialTheme.typography.labelSmall,
    )
}
