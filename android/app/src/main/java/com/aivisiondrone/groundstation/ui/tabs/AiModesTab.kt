package com.aivisiondrone.groundstation.ui.tabs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.control.DroneMode
import com.aivisiondrone.groundstation.control.ModeControls
import com.aivisiondrone.groundstation.telemetry.DetectionsState
import com.aivisiondrone.groundstation.telemetry.RawDetection
import com.aivisiondrone.groundstation.telemetry.TrackingState
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** AI guidance modes (Track/Follow/Orbit/Approach) plus a live list of
 * everything the AI currently sees - lets the operator pick a target from
 * a list instead of needing to tap it on the video, and tune Follow/Orbit
 * parameters without the video feed in the way. */
@Composable
fun AiModesTab(
    viewModel: MainViewModel,
    mode: DroneMode,
    followSeparationM: Float,
    followAltitudeM: Float,
    orbitRadiusM: Float,
    orbitAltitudeM: Float,
    tracking: TrackingState,
    detections: DetectionsState,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("AI Modes", color = DroneColors.TextPrimary, style = MaterialTheme.typography.headlineSmall)

        ModeControls(
            currentMode = mode,
            followSeparationM = followSeparationM,
            followAltitudeM = followAltitudeM,
            orbitRadiusM = orbitRadiusM,
            orbitAltitudeM = orbitAltitudeM,
            onModeSelected = { viewModel.setMode(it) },
            onFollowSeparationChanged = { viewModel.setFollowSeparation(it) },
            onFollowAltitudeChanged = { viewModel.setFollowAltitude(it) },
            onOrbitRadiusChanged = { viewModel.setOrbitRadius(it) },
            onOrbitAltitudeChanged = { viewModel.setOrbitAltitude(it) },
            modifier = Modifier.fillMaxWidth(),
        )

        if (tracking.targetId != null) {
            Card(
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.9f)),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "Current target #${tracking.targetId} - ${tracking.state}" +
                        (tracking.distanceM?.let { "  %.1fm".format(it) } ?: ""),
                    color = DroneColors.TextPrimary,
                    modifier = Modifier.padding(12.dp),
                )
            }
        }

        Text(
            "Live detections (tap Select to lock a target)",
            color = DroneColors.TextSecondary,
            style = MaterialTheme.typography.labelMedium,
        )
        LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth()) {
            items(detections.detections) { detection ->
                DetectionRow(detection = detection, onSelect = {
                    viewModel.selectTargetAtPoint(x = detection.bbox.x + detection.bbox.w / 2, y = detection.bbox.y + detection.bbox.h / 2)
                })
            }
        }
    }
}

@Composable
private fun DetectionRow(detection: RawDetection, onSelect: () -> Unit) {
    Card(
        shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.SurfaceElevated),
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                "${detection.className}  ${(detection.score * 100).toInt()}%",
                color = DroneColors.TextPrimary,
            )
            Button(
                onClick = onSelect,
                colors = ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = androidx.compose.ui.graphics.Color(0xFF00232A)),
            ) {
                Text("Select")
            }
        }
    }
}
