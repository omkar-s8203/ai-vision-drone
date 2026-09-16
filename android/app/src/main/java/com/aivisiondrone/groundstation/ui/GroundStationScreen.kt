package com.aivisiondrone.groundstation.ui

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.toSize
import androidx.compose.ui.viewinterop.AndroidView
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.comms.LinkState
import com.aivisiondrone.groundstation.control.AbortButton
import com.aivisiondrone.groundstation.control.DetectionsOverlay
import com.aivisiondrone.groundstation.control.FlightControlDock
import com.aivisiondrone.groundstation.control.ModeControls
import com.aivisiondrone.groundstation.control.TargetSelectionOverlay
import com.aivisiondrone.groundstation.control.TrackingOverlay
import com.aivisiondrone.groundstation.telemetry.HealthPanel
import com.aivisiondrone.groundstation.telemetry.TelemetryPanel
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import org.webrtc.EglBase
import org.webrtc.SurfaceViewRenderer

private const val DEFAULT_HOST = "192.168.4.1" // typical Pi-as-WiFi-AP gateway address
private const val DEFAULT_PORT = 8765 // matches companion/config/network.yaml ws_port
private const val ASSUMED_VIDEO_WIDTH = 1280.0
private const val ASSUMED_VIDEO_HEIGHT = 720.0

@Composable
fun GroundStationScreen(viewModel: MainViewModel, eglBase: EglBase, context: Context) {
    val linkState by viewModel.linkState.collectAsState()
    val telemetry by viewModel.telemetry.collectAsState()
    val health by viewModel.health.collectAsState()
    val tracking by viewModel.tracking.collectAsState()
    val detections by viewModel.detections.collectAsState()
    val mode by viewModel.mode.collectAsState()
    val followSeparation by viewModel.followSeparationM.collectAsState()
    val followAltitude by viewModel.followAltitudeM.collectAsState()
    val remoteVideoTrack by viewModel.remoteVideoTrack.collectAsState()
    val recording by viewModel.recording.collectAsState()

    var host by remember { mutableStateOf(DEFAULT_HOST) }
    var port by remember { mutableStateOf(DEFAULT_PORT.toString()) }
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
        modifier = Modifier
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

        TrackingOverlay(tracking = tracking, modifier = Modifier.fillMaxSize())

        Column(
            modifier = Modifier.align(Alignment.TopStart).padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            HealthPanel(health = health)
            LinkStatusChip(linkState = linkState)
        }

        TelemetryPanel(
            telemetry = telemetry,
            modifier = Modifier.align(Alignment.TopEnd).padding(8.dp),
        )

        AbortButton(onAbort = { viewModel.abort() }, modifier = Modifier.align(Alignment.BottomEnd))

        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (linkState != LinkState.CONNECTED) {
                Card(
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = DroneColors.Surface.copy(alpha = 0.92f)),
                ) {
                    Row(
                        modifier = Modifier.padding(10.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedTextField(
                            value = host,
                            onValueChange = { host = it },
                            label = { Text("Pi host") },
                            colors = OutlinedTextFieldDefaults.colors(focusedTextColor = DroneColors.TextPrimary, unfocusedTextColor = DroneColors.TextPrimary),
                        )
                        OutlinedTextField(
                            value = port,
                            onValueChange = { port = it },
                            label = { Text("Port") },
                            colors = OutlinedTextFieldDefaults.colors(focusedTextColor = DroneColors.TextPrimary, unfocusedTextColor = DroneColors.TextPrimary),
                        )
                        Button(
                            onClick = { port.toIntOrNull()?.let { viewModel.connect(context, eglBase, host, it) } },
                            colors = ButtonDefaults.buttonColors(containerColor = DroneColors.Accent, contentColor = androidx.compose.ui.graphics.Color(0xFF00232A)),
                        ) { Text("Connect") }
                    }
                }
            }
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
            ModeControls(
                currentMode = mode,
                followSeparationM = followSeparation,
                followAltitudeM = followAltitude,
                onModeSelected = { viewModel.setMode(it) },
                onFollowSeparationChanged = { viewModel.setFollowSeparation(it) },
                onFollowAltitudeChanged = { viewModel.setFollowAltitude(it) },
            )
        }
    }
}

@Composable
private fun LinkStatusChip(linkState: LinkState) {
    val color = when (linkState) {
        LinkState.CONNECTED -> DroneColors.Safe
        LinkState.CONNECTING -> DroneColors.Warning
        LinkState.DISCONNECTED -> DroneColors.Danger
    }
    Card(
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Overlay),
    ) {
        Text(
            text = "LINK: ${linkState.name}",
            color = color,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = androidx.compose.material3.MaterialTheme.typography.labelSmall,
        )
    }
}
