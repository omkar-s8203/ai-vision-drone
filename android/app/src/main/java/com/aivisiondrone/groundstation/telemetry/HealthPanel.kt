package com.aivisiondrone.groundstation.telemetry

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun HealthPanel(health: HealthState, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .background(Color.Black.copy(alpha = 0.55f))
            .padding(8.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
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
            color = Color.White,
        )
    }
}

@Composable
private fun HealthDot(label: String, ok: Boolean) {
    Text(text = "$label ${if (ok) "OK" else "--"}", color = if (ok) Color.Green else Color.Red)
}
