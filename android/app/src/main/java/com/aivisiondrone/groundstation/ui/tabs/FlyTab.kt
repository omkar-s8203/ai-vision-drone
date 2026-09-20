package com.aivisiondrone.groundstation.ui.tabs

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.toSize
import androidx.compose.ui.viewinterop.AndroidView
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.control.DetectionsOverlay
import com.aivisiondrone.groundstation.control.DroneMode
import com.aivisiondrone.groundstation.control.GuidanceCommandPanel
import com.aivisiondrone.groundstation.control.GuidanceWarningBanner
import com.aivisiondrone.groundstation.control.RecordButton
import com.aivisiondrone.groundstation.control.TargetActionSheet
import com.aivisiondrone.groundstation.control.TargetSelectionOverlay
import com.aivisiondrone.groundstation.control.TrackingOverlay
import com.aivisiondrone.groundstation.telemetry.DetectionsState
import com.aivisiondrone.groundstation.telemetry.HealthPanel
import com.aivisiondrone.groundstation.telemetry.HealthState
import com.aivisiondrone.groundstation.telemetry.RecordingState
import com.aivisiondrone.groundstation.telemetry.TelemetryPanel
import com.aivisiondrone.groundstation.telemetry.TelemetryState
import com.aivisiondrone.groundstation.telemetry.TrackingState
import com.aivisiondrone.groundstation.ui.LinkStatusChip
import com.aivisiondrone.groundstation.comms.LinkState
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import org.webrtc.EglBase
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoTrack

private const val ASSUMED_VIDEO_WIDTH = 1280.0
private const val ASSUMED_VIDEO_HEIGHT = 720.0

/**
 * The main flight view: live video, all detections, the tracked target
 * (with an orbit ring when Orbit mode is active), tap/drag selection, and
 * the quick health/telemetry chips - the DJI-Fly-style default screen the
 * operator spends most of their time on.
 */
@Composable
fun FlyTab(
    viewModel: MainViewModel,
    eglBase: EglBase,
    context: Context,
    linkState: LinkState,
    telemetry: TelemetryState,
    health: HealthState,
    tracking: TrackingState,
    detections: DetectionsState,
    mode: DroneMode,
    remoteVideoTrack: VideoTrack?,
    showTargetActionSheet: Boolean,
    recording: RecordingState,
    onToggleRecording: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var rendererRef by remember { mutableStateOf<SurfaceViewRenderer?>(null) }
    var overlaySizePx by remember { mutableStateOf(Size.Zero) }

    val videoWidth = tracking.imageWidth?.toDouble() ?: ASSUMED_VIDEO_WIDTH
    val videoHeight = tracking.imageHeight?.toDouble() ?: ASSUMED_VIDEO_HEIGHT

    DisposableEffect(remoteVideoTrack, rendererRef) {
        val renderer = rendererRef
        val track = remoteVideoTrack
        if (renderer != null && track != null) {
            track.addSink(renderer)
        }
        onDispose {
            if (renderer != null && track != null) {
                track.removeSink(renderer)
            }
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .onSizeChanged { overlaySizePx = it.toSize() },
    ) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                SurfaceViewRenderer(ctx).apply {
                    init(eglBase.eglBaseContext, null)
                    setMirror(false)
                    rendererRef = this
                }
            },
        )

        // HUD Crosshair
        HUDCrosshair(Modifier.align(Alignment.Center))

        DetectionsOverlay(detections = detections, modifier = Modifier.fillMaxSize())

        TargetSelectionOverlay(
            modifier = Modifier.fillMaxSize(),
            onTapSelect = { point ->
                if (overlaySizePx.width > 0f && overlaySizePx.height > 0f) {
                    val scaleX = videoWidth / overlaySizePx.width
                    val scaleY = videoHeight / overlaySizePx.height
                    viewModel.selectTargetAtPoint(x = point.x * scaleX, y = point.y * scaleY)
                }
            },
            onSelectionComplete = { rect: Rect ->
                if (overlaySizePx.width > 0f && overlaySizePx.height > 0f) {
                    val scaleX = videoWidth / overlaySizePx.width
                    val scaleY = videoHeight / overlaySizePx.height
                    viewModel.selectTarget(
                        x = rect.left * scaleX,
                        y = rect.top * scaleY,
                        w = rect.width * scaleX,
                        h = rect.height * scaleY,
                    )
                }
            },
        )

        TrackingOverlay(
            tracking = tracking,
            orbiting = mode == DroneMode.ORBITING,
            modifier = Modifier.fillMaxSize(),
        )

        // TOP BAR HUD
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(androidx.compose.ui.graphics.Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.8f), Color.Transparent)))
                .padding(horizontal = 20.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Top
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                HealthPanel(health = health)
                LinkStatusChip(linkState = linkState)
            }
            
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                // gpsFixType follows MAV_GPS_FIX_TYPE (3+ = 3D fix or better) -
                // the real, authoritative signal from GPS_RAW_INT, not an
                // inferred proxy from lat being non-null (a stale/degraded
                // fix can still report a non-null last-known position).
                val hasFix = (telemetry.gpsFixType ?: 0) >= 3
                HUDTelemetryItem(label = "GPS", value = if (hasFix) "FIX" else "NO FIX", color = if (hasFix) DroneColors.Safe else DroneColors.Danger)
                HUDTelemetryItem(label = "SAT", value = telemetry.satellitesVisible?.toString() ?: "--", color = DroneColors.TextPrimary)
                // Previously used two different fallbacks for the same null
                // field (0 for the displayed text, 100 for the color check),
                // so "no telemetry yet" rendered as a self-contradictory
                // "0% BAT" in Safe/green. Missing data now reads "--" in a
                // neutral color, matching SAT/ALT/SPD elsewhere.
                val batteryPct = telemetry.batteryRemainingPct
                HUDTelemetryItem(
                    label = "BAT",
                    value = batteryPct?.let { "$it%" } ?: "--",
                    color = when {
                        batteryPct == null -> DroneColors.TextPrimary
                        batteryPct < 20 -> DroneColors.Danger
                        else -> DroneColors.Safe
                    },
                )
            }
        }

        // RIGHT HUD PANEL
        Column(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(end = 20.dp),
            horizontalAlignment = Alignment.End,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            TelemetryPanel(telemetry = telemetry)
            GuidanceCommandPanel(tracking = tracking)
        }

        // RECORD CONTROLS
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 20.dp, bottom = 20.dp)
        ) {
            RecordButton(
                recording = recording.recording,
                durationS = recording.durationS,
                onClick = onToggleRecording
            )
        }

        tracking.guidanceReason?.let { reason ->
            GuidanceWarningBanner(
                reason = reason,
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(top = 80.dp),
            )
        }

        if (showTargetActionSheet) {
            TargetActionSheet(
                onTrack = { viewModel.chooseTargetAction(DroneMode.TRACKING) },
                onFollow = { viewModel.chooseTargetAction(DroneMode.FOLLOWING) },
                onOrbit = { viewModel.chooseTargetAction(DroneMode.ORBITING) },
                onCancel = { viewModel.cancelTargetSelection() },
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 32.dp)
                    .fillMaxWidth(0.6f),
            )
        }
    }
}

@Composable
private fun HUDCrosshair(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(40.dp)
            .alpha(0.4f),
        contentAlignment = Alignment.Center
    ) {
        Box(modifier = Modifier.size(24.dp, 1.5.dp).background(Color.White))
        Box(modifier = Modifier.size(1.5.dp, 24.dp).background(Color.White))
    }
}

@Composable
private fun HUDTelemetryItem(label: String, value: String, color: Color) {
    Column(horizontalAlignment = Alignment.End) {
        Text(label, color = DroneColors.TextSecondary, style = MaterialTheme.typography.labelSmall)
        Text(value, color = color, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
    }
}
