package com.aivisiondrone.groundstation.ui.tabs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.control.DroneMode
import com.aivisiondrone.groundstation.control.GridSearchControls
import com.aivisiondrone.groundstation.control.ModeControls
import com.aivisiondrone.groundstation.telemetry.RawDetection
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** AI guidance modes (Track/Follow/Orbit/Approach) plus a live list of
 * everything the AI currently sees - lets the operator pick a target from
 * a list instead of needing to tap it on the video, and tune Follow/Orbit
 * parameters without the video feed in the way.
 *
 * Collects `tracking`/`detections` (both update on essentially every
 * processed frame on the Pi) itself rather than receiving them as
 * parameters - see FlyTab.kt's docstring for the whole-screen-recomposition
 * bug this avoids. */
@Composable
fun AiModesTab(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier,
) {
    val mode by viewModel.mode.collectAsState()
    val followSeparationM by viewModel.followSeparationM.collectAsState()
    val followAltitudeM by viewModel.followAltitudeM.collectAsState()
    val orbitRadiusM by viewModel.orbitRadiusM.collectAsState()
    val orbitAltitudeM by viewModel.orbitAltitudeM.collectAsState()
    val followMaxSpeedMps by viewModel.followMaxSpeedMps.collectAsState()
    val orbitMaxSpeedMps by viewModel.orbitMaxSpeedMps.collectAsState()
    val tracking by viewModel.tracking.collectAsState()
    val detections by viewModel.detections.collectAsState()
    val gridSearchState by viewModel.gridSearchState.collectAsState()
    val telemetry by viewModel.telemetry.collectAsState()
    // Local-only: whether the Grid Search config panel is open. Unlike
    // every other mode, tapping its row button must not immediately send a
    // mode_command (it has no width/height yet) - it only opens this panel;
    // the real command is sent from inside GridSearchControls once "Start
    // Grid Search" is tapped. Kept closed by selecting any other mode, so
    // the panel no longer sits permanently visible under every mode the way
    // it used to (a real gap: it was rendered unconditionally regardless of
    // which mode was actually selected).
    var gridSearchPanelOpen by remember { mutableStateOf(false) }
    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        item {
            Spacer(modifier = Modifier.height(20.dp))
            Text(
                "AI Modes",
                color = DroneColors.TextPrimary,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(start = 4.dp)
            )
        }

        item {
            ModeControls(
                currentMode = mode,
                followSeparationM = followSeparationM,
                followAltitudeM = followAltitudeM,
                orbitRadiusM = orbitRadiusM,
                orbitAltitudeM = orbitAltitudeM,
                followMaxSpeedMps = followMaxSpeedMps,
                orbitMaxSpeedMps = orbitMaxSpeedMps,
                onModeSelected = { selected ->
                    if (selected == DroneMode.GRID_SEARCH) {
                        gridSearchPanelOpen = !gridSearchPanelOpen
                    } else {
                        gridSearchPanelOpen = false
                        viewModel.setMode(selected)
                    }
                },
                onFollowSeparationChanged = { viewModel.setFollowSeparation(it) },
                onFollowAltitudeChanged = { viewModel.setFollowAltitude(it) },
                onOrbitRadiusChanged = { viewModel.setOrbitRadius(it) },
                onOrbitAltitudeChanged = { viewModel.setOrbitAltitude(it) },
                onFollowMaxSpeedChanged = { viewModel.setFollowMaxSpeed(it) },
                onOrbitMaxSpeedChanged = { viewModel.setOrbitMaxSpeed(it) },
                gridSearchSelected = gridSearchPanelOpen || gridSearchState.active,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        // Only shown while actually being configured or actually running -
        // stays out of the way of every other mode's screen otherwise.
        if (gridSearchPanelOpen || gridSearchState.active) {
            item {
                GridSearchControls(
                    gridSearchState = gridSearchState,
                    hasGpsFix = (telemetry.gpsFixType ?: 0) >= 3,
                    onStart = { widthM, heightM -> viewModel.startGridSearch(widthM, heightM) },
                    onStop = { viewModel.stopGridSearch() },
                    onCancel = { gridSearchPanelOpen = false },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        if (tracking.targetId != null) {
            item {
                Card(
                    shape = RoundedCornerShape(20.dp),
                    colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "Target #${tracking.targetId} • ${tracking.state}" +
                                (tracking.distanceM?.let { " • %.1fm".format(it) } ?: ""),
                        color = DroneColors.TextPrimary,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier.padding(20.dp),
                    )
                }
            }
        }

        item {
            Text(
                "DETECTIONS",
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(start = 4.dp, top = 8.dp)
            )
        }

        if (detections.detections.isEmpty()) {
            item {
                Text(
                    "Nothing detected right now - point the camera at a person, vehicle, or other object.",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(horizontal = 4.dp, vertical = 8.dp),
                )
            }
        }

        items(detections.detections) { detection ->
            DetectionRow(detection = detection, onSelect = {
                viewModel.selectTargetAtPoint(
                    x = detection.bbox.x + detection.bbox.w / 2,
                    y = detection.bbox.y + detection.bbox.h / 2
                )
            })
        }

        item {
            Spacer(modifier = Modifier.height(20.dp))
        }
    }
}

@Composable
private fun DetectionRow(detection: RawDetection, onSelect: () -> Unit) {
    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
        modifier = Modifier
            .fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    detection.className.uppercase(),
                    color = DroneColors.TextPrimary,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    "Confidence: ${(detection.score * 100).toInt()}%",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.labelMedium
                )
            }
            Button(
                onClick = onSelect,
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = DroneColors.Accent,
                    contentColor = Color.Black
                ),
                modifier = Modifier.height(36.dp)
            ) {
                Text("Select", fontWeight = FontWeight.Black)
            }
        }
    }
}
