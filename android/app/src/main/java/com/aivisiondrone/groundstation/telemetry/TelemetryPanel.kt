package com.aivisiondrone.groundstation.telemetry

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun TelemetryPanel(telemetry: TelemetryState, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .background(Color.Black.copy(alpha = 0.55f))
            .padding(8.dp),
    ) {
        Text("Mode: ${telemetry.flightMode ?: "--"}  ${if (telemetry.armed) "ARMED" else "DISARMED"}", color = Color.White)
        Text("GPS: ${telemetry.lat?.let { "%.5f".format(it) } ?: "--"}, ${telemetry.lon?.let { "%.5f".format(it) } ?: "--"}", color = Color.White)
        Text("Alt: ${telemetry.altitudeM?.let { "%.1f m".format(it) } ?: "--"}   Speed: ${telemetry.groundspeedMps?.let { "%.1f m/s".format(it) } ?: "--"}", color = Color.White)
        Text("Battery: ${telemetry.batteryVoltage?.let { "%.1f V".format(it) } ?: "--"}  ${telemetry.batteryRemainingPct?.let { "$it%" } ?: ""}", color = Color.White)
    }
}
