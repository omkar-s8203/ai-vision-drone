package com.aivisiondrone.groundstation.ui.tabs

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import android.content.Context
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.toSize
import androidx.compose.ui.viewinterop.AndroidView
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.R
import com.aivisiondrone.groundstation.comms.LinkState
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
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    androidx.compose.ui.graphics.Brush.verticalGradient(
                        0f to Color.Black.copy(alpha = 0.95f),
                        0.8f to Color.Black.copy(alpha = 0.6f),
                        1f to Color.Transparent
                    )
                )
                .statusBarsPadding()
                .padding(horizontal = 24.dp, vertical = 14.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Image(
                            painter = painterResource(id = R.drawable.app_logo),
                            contentDescription = "App Logo",
                            modifier = Modifier.size(32.dp)
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        HealthPanel(health = health)
                    }
                    // Link status now integrated more cleanly
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .background(DroneColors.Overlay, RoundedCornerShape(8.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Box(
                            modifier = Modifier
                                .size(7.dp)
                                .background(
                                    if (linkState == LinkState.CONNECTED) DroneColors.Safe else DroneColors.Danger,
                                    androidx.compose.foundation.shape.CircleShape
                                )
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = if (linkState == LinkState.CONNECTED) "LINK: CONNECTED" else "LINK: DISCONNECTED",
                            color = if (linkState == LinkState.CONNECTED) DroneColors.TextPrimary else DroneColors.Danger,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Black,
                            letterSpacing = 0.5.sp
                        )
                    }
                }
                
                Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    val hasFix = (telemetry.gpsFixType ?: 0) >= 3
                    HUDTelemetryItem(label = "GPS", value = if (hasFix) "FIX" else "NO FIX", color = if (hasFix) DroneColors.Safe else DroneColors.Danger)
                    HUDTelemetryItem(label = "SAT", value = telemetry.satellitesVisible?.toString() ?: "--", color = DroneColors.TextPrimary)
                    HUDTelemetryItem(label = "RSSI", value = telemetry.rcRssiPct?.let { "$it%" } ?: "--", color = DroneColors.TextPrimary)

                    val batteryPct = telemetry.batteryRemainingPct
                    val isLowBattery = batteryPct != null && batteryPct < 20
                    
                    val infiniteTransition = rememberInfiniteTransition(label = "BatteryPulse")
                    val alpha by if (isLowBattery) {
                        infiniteTransition.animateFloat(
                            initialValue = 0.4f,
                            targetValue = 1f,
                            animationSpec = infiniteRepeatable(
                                animation = tween(500),
                                repeatMode = RepeatMode.Reverse
                            ),
                            label = "AlphaPulse"
                        )
                    } else {
                        remember { mutableStateOf(1f) }
                    }

                    HUDTelemetryItem(
                        label = "BAT",
                        value = batteryPct?.let { "$it%" } ?: "--",
                        color = when {
                            batteryPct == null -> DroneColors.TextPrimary
                            batteryPct < 20 -> DroneColors.Danger
                            else -> DroneColors.Safe
                        },
                        modifier = Modifier.alpha(alpha)
                    )
                }
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

        AnimatedVisibility(
            visible = tracking.guidanceReason != null,
            enter = slideInVertically(initialOffsetY = { -it }) + fadeIn(),
            exit = slideOutVertically(targetOffsetY = { -it }) + fadeOut(),
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 80.dp)
        ) {
            tracking.guidanceReason?.let { reason ->
                GuidanceWarningBanner(reason = reason)
            }
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
            .size(48.dp)
            .alpha(0.6f),
        contentAlignment = Alignment.Center
    ) {
        // Shadow/glow for visibility
        Box(modifier = Modifier.size(26.dp, 2.5.dp).background(Color.Black.copy(alpha = 0.3f)))
        Box(modifier = Modifier.size(2.5.dp, 26.dp).background(Color.Black.copy(alpha = 0.3f)))
        
        // Main lines
        Box(modifier = Modifier.size(24.dp, 1.2.dp).background(Color.White))
        Box(modifier = Modifier.size(1.2.dp, 24.dp).background(Color.White))
        
        // Center precision dot
        Box(modifier = Modifier.size(2.dp).background(DroneColors.Accent, androidx.compose.foundation.shape.CircleShape))
    }
}

@Composable
private fun HUDTelemetryItem(label: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Column(
        horizontalAlignment = Alignment.End,
        modifier = modifier
            .background(DroneColors.Overlay, RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp)
            .width(64.dp) // Fixed width for alignment consistency
    ) {
        Text(
            text = label, 
            color = DroneColors.TextSecondary, 
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = value, 
            color = color, 
            style = MaterialTheme.typography.bodyMedium, 
            fontWeight = FontWeight.Black,
            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
        )
    }
}
