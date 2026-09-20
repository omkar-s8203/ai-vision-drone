package com.aivisiondrone.groundstation.telemetry

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

@Composable
fun TelemetryPanel(telemetry: TelemetryState, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.width(180.dp),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Overlay),
        border = androidx.compose.foundation.BorderStroke(0.5.dp, DroneColors.SurfaceElevated)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                text = telemetry.flightMode ?: "DISCONNECTED",
                color = DroneColors.Accent,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Black,
            )
            Text(
                text = if (telemetry.armed) "ARMED" else "SAFE",
                color = if (telemetry.armed) DroneColors.Danger else DroneColors.Safe,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.ExtraBold,
            )
            
            Spacer(modifier = Modifier.height(8.dp))

            TelemetryRow("ALT", "${telemetry.altitudeM?.let { "%.1f m".format(it) } ?: "--"}")
            TelemetryRow("SPD", "${telemetry.groundspeedMps?.let { "%.1f m/s".format(it) } ?: "--"}")
            
            if (telemetry.fenceEnabled) {
                TelemetryRow(
                    "FENCE",
                    if (telemetry.fenceBreached) "BREACH" else "OK",
                    color = if (telemetry.fenceBreached) DroneColors.Danger else DroneColors.Safe
                )
            }
        }
    }
}

@Composable
private fun TelemetryRow(label: String, value: String, color: Color = DroneColors.TextPrimary) {
    androidx.compose.foundation.layout.Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
        horizontalArrangement = androidx.compose.foundation.layout.Arrangement.SpaceBetween
    ) {
        Text(label, color = DroneColors.TextSecondary, style = MaterialTheme.typography.labelSmall)
        Text(value, color = color, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
    }
}
