package com.aivisiondrone.groundstation.ui.tabs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.control.FlightControlDock
import com.aivisiondrone.groundstation.telemetry.RecordingState
import com.aivisiondrone.groundstation.telemetry.TelemetryPanel
import com.aivisiondrone.groundstation.telemetry.TelemetryState
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** Direct flight-controller commands - arm/disarm, FC flight mode, and
 * video recording - given their own full screen rather than squeezed
 * beneath the video, since these are the highest-consequence actions in
 * the app (arming spins the motors). */
@Composable
fun ControlTab(
    viewModel: MainViewModel,
    telemetry: TelemetryState,
    recording: RecordingState,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            "Flight Control",
            color = DroneColors.TextPrimary,
            style = MaterialTheme.typography.headlineSmall,
        )
        TelemetryPanel(telemetry = telemetry, modifier = Modifier.fillMaxWidth())
        FlightControlDock(
            armed = telemetry.armed,
            flightMode = telemetry.flightMode,
            recording = recording.recording,
            recordingDurationS = recording.durationS,
            onArmChanged = { viewModel.setArmed(it) },
            onFlightModeSelected = { viewModel.setFlightMode(it) },
            onToggleRecording = { viewModel.toggleRecording() },
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "Arming/disarming and flight-mode changes go straight to the flight " +
                "controller, independent of the AI guidance mode selected in the AI " +
                "Modes tab. The RC transmitter's mode switch always overrides both.",
            color = DroneColors.TextSecondary,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
