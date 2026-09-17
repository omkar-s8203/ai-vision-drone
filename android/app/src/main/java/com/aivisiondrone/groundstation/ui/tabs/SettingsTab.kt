package com.aivisiondrone.groundstation.ui.tabs

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.comms.LinkState
import com.aivisiondrone.groundstation.ui.LinkStatusChip
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import org.webrtc.EglBase

private const val DEFAULT_HOST = "192.168.4.1" // typical Pi-as-WiFi-AP gateway address
private const val DEFAULT_PORT = 8765 // matches companion/config/network.yaml ws_port

/** Connection settings - the Pi's host/port and connect/disconnect, kept
 * out of the main flight view so the video surface doesn't have to make
 * room for a text field the operator only touches once per session. */
@Composable
fun SettingsTab(
    viewModel: MainViewModel,
    eglBase: EglBase,
    context: Context,
    linkState: LinkState,
    modifier: Modifier = Modifier,
) {
    var host by remember { mutableStateOf(DEFAULT_HOST) }
    var port by remember { mutableStateOf(DEFAULT_PORT.toString()) }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Settings", color = DroneColors.TextPrimary, style = MaterialTheme.typography.headlineSmall)

        Card(
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.92f)),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Pi Connection", color = DroneColors.TextPrimary, style = MaterialTheme.typography.titleMedium)
                LinkStatusChip(linkState = linkState)
                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("Pi host") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(focusedTextColor = DroneColors.TextPrimary, unfocusedTextColor = DroneColors.TextPrimary),
                )
                OutlinedTextField(
                    value = port,
                    onValueChange = { port = it },
                    label = { Text("Port") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(focusedTextColor = DroneColors.TextPrimary, unfocusedTextColor = DroneColors.TextPrimary),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        onClick = { port.toIntOrNull()?.let { viewModel.connect(context, eglBase, host, it) } },
                        colors = ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = Color(0xFF00232A)),
                    ) { Text("Connect") }
                    OutlinedButton(onClick = { viewModel.disconnect() }) {
                        Text("Disconnect", color = DroneColors.TextPrimary)
                    }
                }
            }
        }

        Text(
            "AI Vision Drone Ground Station - companion computer control app. " +
                "The flight controller remains the sole flight authority at all " +
                "times; the RC transmitter's mode switch always overrides this app.",
            color = DroneColors.TextSecondary,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
