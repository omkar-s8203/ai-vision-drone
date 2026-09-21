package com.aivisiondrone.groundstation.ui.tabs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.control.FlightControlDock
import com.aivisiondrone.groundstation.telemetry.TelemetryPanel
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** Direct flight-controller commands - arm/disarm and FC flight mode -
 * given their own full screen rather than squeezed beneath the video,
 * since these are the highest-consequence actions in the app (arming spins
 * the motors). Video recording lives on the Fly tab instead, next to the
 * camera view it actually controls.
 *
 * Collects `telemetry` itself rather than receiving it as a parameter -
 * see FlyTab.kt's docstring for why threading a per-frame-updating flow
 * through a shared parent composable causes unnecessary whole-screen
 * recomposition. */
@Composable
fun ControlTab(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier,
) {
    val telemetry by viewModel.telemetry.collectAsState()
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        Spacer(modifier = Modifier.height(20.dp))
        Text(
            "Flight Control",
            color = DroneColors.TextPrimary,
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(start = 4.dp)
        )
        TelemetryPanel(telemetry = telemetry, modifier = Modifier.fillMaxWidth())
        FlightControlDock(
            armed = telemetry.armed,
            flightMode = telemetry.flightMode,
            onArmChanged = { viewModel.setArmed(it) },
            onForceDisarm = { viewModel.setArmed(false, force = true) },
            onFlightModeSelected = { viewModel.setFlightMode(it) },
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "Arming/disarming and flight-mode changes go straight to the flight " +
                "controller, independent of the AI guidance mode selected in the AI " +
                "Modes tab. The RC transmitter's mode switch always overrides both.",
            color = DroneColors.TextSecondary,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(horizontal = 4.dp)
        )
        Spacer(modifier = Modifier.height(20.dp))
    }
}
