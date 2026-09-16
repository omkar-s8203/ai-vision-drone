package com.aivisiondrone.groundstation.telemetry

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

@Composable
fun TelemetryPanel(telemetry: TelemetryState, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Overlay),
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Text(
                text = telemetry.flightMode ?: "--",
                color = DroneColors.TextPrimary,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = if (telemetry.armed) "ARMED" else "DISARMED",
                color = if (telemetry.armed) DroneColors.Danger else DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "GPS: ${telemetry.lat?.let { "%.5f".format(it) } ?: "--"}, ${telemetry.lon?.let { "%.5f".format(it) } ?: "--"}",
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelSmall,
            )
            Text(
                "Alt: ${telemetry.altitudeM?.let { "%.1f m".format(it) } ?: "--"}   Speed: ${telemetry.groundspeedMps?.let { "%.1f m/s".format(it) } ?: "--"}",
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelSmall,
            )
            Text(
                "Battery: ${telemetry.batteryVoltage?.let { "%.1f V".format(it) } ?: "--"}  ${telemetry.batteryRemainingPct?.let { "$it%" } ?: ""}",
                color = if ((telemetry.batteryRemainingPct ?: 100) < 20) DroneColors.Danger else DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
