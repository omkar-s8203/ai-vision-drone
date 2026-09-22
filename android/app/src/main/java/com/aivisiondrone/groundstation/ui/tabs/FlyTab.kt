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
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
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
import com.aivisiondrone.groundstation.control.DetectionHeatmapOverlay
import com.aivisiondrone.groundstation.control.DetectionsOverlay
import com.aivisiondrone.groundstation.control.DroneMode
import com.aivisiondrone.groundstation.control.PerimeterZoneEditOverlay
import com.aivisiondrone.groundstation.control.PerimeterZoneOverlay
import com.aivisiondrone.groundstation.control.TargetTrailOverlay
import com.aivisiondrone.groundstation.control.GuidanceCommandPanel
import com.aivisiondrone.groundstation.control.GuidanceWarningBanner
import com.aivisiondrone.groundstation.control.RecordButton
import com.aivisiondrone.groundstation.control.TargetActionSheet
import com.aivisiondrone.groundstation.control.TargetSelectionOverlay
import com.aivisiondrone.groundstation.control.TrackingOverlay
import com.aivisiondrone.groundstation.telemetry.TargetBBox
import com.aivisiondrone.groundstation.telemetry.HealthPanel
import com.aivisiondrone.groundstation.telemetry.TelemetryPanel
import com.aivisiondrone.groundstation.ui.LinkStatusChip
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import org.webrtc.EglBase
import org.webrtc.SurfaceViewRenderer

private const val ASSUMED_VIDEO_WIDTH = 1280.0
private const val ASSUMED_VIDEO_HEIGHT = 720.0

// Continuous guidance modes worth offering a "Resume" tap for after an RC
// override/FC-not-Guided rejection - Grid Search already reverts its own
// button to unselected on rejection (see MainViewModel's ONE_SHOT_MODES
// handling) rather than staying selected waiting to resume, and
// Idle/Tracking never had guidance running in the first place.
private val RESUMABLE_GUIDANCE_MODES = setOf(DroneMode.FOLLOWING, DroneMode.ORBITING, DroneMode.APPROACHING)

/**
 * The main flight view: live video, all detections, the tracked target
 * (with an orbit ring when Orbit mode is active), tap/drag selection, and
 * the quick health/telemetry chips - the DJI-Fly-style default screen the
 * operator spends most of their time on.
 *
 * Collects its own state directly from `viewModel` (telemetry/health/
 * tracking/detections/recording/remoteVideoTrack/mode/linkState/
 * showTargetActionSheet) rather than receiving it all as parameters from
 * `GroundStationScreen` - a real smoothness bug found and fixed: these
 * flows update on essentially every processed frame on the Pi (up to the
 * camera's target FPS), and `GroundStationScreen` used to `collectAsState()`
 * all of them itself before threading them down as parameters. Since
 * recomposition scope is the composable that actually reads the changed
 * state, that meant *the entire screen* - nav bar, abort button, tab
 * switcher and all - was recomposing 20-30 times a second regardless of
 * which tab was even open, not just this one. Collecting here instead
 * confines that recomposition to just this tab, which is the one screen
 * that's actually supposed to update that often.
 */
@Composable
fun FlyTab(
    viewModel: MainViewModel,
    eglBase: EglBase,
    context: Context,
    modifier: Modifier = Modifier,
) {
    val linkState by viewModel.linkState.collectAsState()
    val telemetry by viewModel.telemetry.collectAsState()
    val health by viewModel.health.collectAsState()
    val tracking by viewModel.tracking.collectAsState()
    val detections by viewModel.detections.collectAsState()
    val mode by viewModel.mode.collectAsState()
    val remoteVideoTrack by viewModel.remoteVideoTrack.collectAsState()
    val showTargetActionSheet by viewModel.showTargetActionSheet.collectAsState()
    val recording by viewModel.recording.collectAsState()
    val heatmapSnapshot by viewModel.heatmapSnapshot.collectAsState()
    val showHeatmap by viewModel.showHeatmap.collectAsState()
    val trailSnapshot by viewModel.trailSnapshot.collectAsState()
    val perimeterZone by viewModel.perimeterZone.collectAsState()
    val perimeterBreached by viewModel.perimeterBreached.collectAsState()

    var rendererRef by remember { mutableStateOf<SurfaceViewRenderer?>(null) }
    var overlaySizePx by remember { mutableStateOf(Size.Zero) }
    // Local, transient UI mode - not ViewModel state, since it's purely
    // "which drag gesture is active right now," never needed outside this
    // composable. Drag-to-define exits automatically once a zone is drawn
    // (see the PerimeterZoneEditOverlay callback below).
    var perimeterEditMode by remember { mutableStateOf(false) }

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

        // A real polish gap: with no video track yet, the operator saw a
        // plain black rectangle with zero explanation - indistinguishable
        // from "the app is broken" to someone who hasn't memorized what a
        // blank SurfaceViewRenderer looks like. Distinguishes "not
        // connected at all" (nothing to wait for) from "connected, video
        // negotiation still in progress" (a spinner - it should arrive
        // shortly) - the plan's own M6 acceptance criteria calls out that
        // "no video" must read differently from other failure states.
        if (remoteVideoTrack == null) {
            NoVideoPlaceholder(linkState = linkState, modifier = Modifier.fillMaxSize())
        }

        if (showHeatmap) {
            DetectionHeatmapOverlay(snapshot = heatmapSnapshot, modifier = Modifier.fillMaxSize())
        }

        // HUD Crosshair
        HUDCrosshair(Modifier.align(Alignment.Center))

        DetectionsOverlay(detections = detections, modifier = Modifier.fillMaxSize())

        PerimeterZoneOverlay(
            zone = perimeterZone,
            breached = perimeterBreached,
            imageWidth = videoWidth.toInt(),
            imageHeight = videoHeight.toInt(),
            modifier = Modifier.fillMaxSize(),
        )

        // Mutually exclusive with target selection below - the operator is
        // either drawing the perimeter zone or selecting a target, never
        // both at once, so the two drag gestures can't conflict.
        if (perimeterEditMode) {
            PerimeterZoneEditOverlay(
                modifier = Modifier.fillMaxSize(),
                onZoneDefined = { rect: Rect ->
                    if (overlaySizePx.width > 0f && overlaySizePx.height > 0f) {
                        val scaleX = videoWidth / overlaySizePx.width
                        val scaleY = videoHeight / overlaySizePx.height
                        viewModel.setPerimeterZone(
                            TargetBBox(
                                x = rect.left * scaleX,
                                y = rect.top * scaleY,
                                w = rect.width * scaleX,
                                h = rect.height * scaleY,
                            )
                        )
                    }
                    perimeterEditMode = false
                },
            )
        } else {
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
        }

        TargetTrailOverlay(snapshot = trailSnapshot, modifier = Modifier.fillMaxSize())

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
                    // Link status - a real polish bug fixed here:
                    // CONNECTING (actively auto-reconnecting after a drop -
                    // see MainViewModel's reconnect loop) used to render
                    // identically to DISCONNECTED (dead, no attempt in
                    // progress), leaving the operator unable to tell "it's
                    // trying" from "it's given up" on the one screen they
                    // actually watch during flight. All three LinkState
                    // values now get their own color/label, matching
                    // LinkStatusChip's own (correct) handling on Settings.
                    val (linkDotColor, linkLabel, linkTextColor) = when (linkState) {
                        LinkState.CONNECTED -> Triple(DroneColors.Safe, "LINK: CONNECTED", DroneColors.TextPrimary)
                        LinkState.CONNECTING -> Triple(DroneColors.Warning, "LINK: RECONNECTING…", DroneColors.Warning)
                        LinkState.DISCONNECTED -> Triple(DroneColors.Danger, "LINK: DISCONNECTED", DroneColors.Danger)
                    }
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .background(DroneColors.Overlay, RoundedCornerShape(8.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Box(
                            modifier = Modifier
                                .size(7.dp)
                                .background(linkDotColor, androidx.compose.foundation.shape.CircleShape)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = linkLabel,
                            color = linkTextColor,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Black,
                            letterSpacing = 0.5.sp
                        )
                    }

                    // Detection-density heatmap toggle - off by default so
                    // it doesn't clutter the live view unasked (a field
                    // request: "can we add a heatmap-like feature").
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .background(
                                if (showHeatmap) DroneColors.Accent.copy(alpha = 0.25f) else DroneColors.Overlay,
                                RoundedCornerShape(8.dp),
                            )
                            .clickable { viewModel.setShowHeatmap(!showHeatmap) }
                            .padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Text(
                            text = if (showHeatmap) "HEATMAP: ON" else "HEATMAP: OFF",
                            color = if (showHeatmap) DroneColors.Accent else DroneColors.TextSecondary,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Black,
                            letterSpacing = 0.5.sp
                        )
                    }

                    // Perimeter/intrusion zone toggle - a defence-relevant
                    // field request ("perimeter / intrusion alert"). Tap
                    // cycle: no zone -> drag to draw one -> zone set (tap
                    // again clears it). Red while a live detection is
                    // actually inside the zone, matching the buzzer firing.
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .background(
                                when {
                                    perimeterBreached -> DroneColors.Danger.copy(alpha = 0.35f)
                                    perimeterEditMode -> DroneColors.Warning.copy(alpha = 0.25f)
                                    perimeterZone != null -> DroneColors.Accent.copy(alpha = 0.25f)
                                    else -> DroneColors.Overlay
                                },
                                RoundedCornerShape(8.dp),
                            )
                            .clickable {
                                when {
                                    perimeterEditMode -> perimeterEditMode = false // cancel drawing
                                    perimeterZone != null -> viewModel.clearPerimeterZone()
                                    else -> perimeterEditMode = true // start drawing
                                }
                            }
                            .padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Text(
                            text = when {
                                perimeterBreached -> "PERIMETER: BREACH"
                                perimeterEditMode -> "PERIMETER: DRAW ZONE"
                                perimeterZone != null -> "PERIMETER: SET"
                                else -> "PERIMETER: OFF"
                            },
                            color = when {
                                perimeterBreached -> DroneColors.Danger
                                perimeterEditMode -> DroneColors.Warning
                                perimeterZone != null -> DroneColors.Accent
                                else -> DroneColors.TextSecondary
                            },
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
                onClick = { viewModel.toggleRecording() }
            )
        }

        AnimatedVisibility(
            // A real error-handling gap: tracking.guidanceReason is a
            // frozen snapshot from the last tracking_update actually
            // received - it is never cleared on its own if the link drops
            // (parseTracking() only runs when a new message arrives).
            // Without the linkState check, a dropped connection while this
            // banner was showing left it stuck on screen indefinitely,
            // "Resume" button and all, even though tapping it could do
            // nothing (client.sendModeCommand() silently no-ops with no
            // open socket) - exactly the kind of stuck/confusing state with
            // no way out that isn't acceptable here. The LINK status chip
            // below is the one source of truth for connectivity; this
            // banner defers to it and reappears fresh, from a real
            // tracking_update, once reconnected.
            visible = tracking.guidanceReason != null && linkState == LinkState.CONNECTED,
            enter = slideInVertically(initialOffsetY = { -it }) + fadeIn(),
            exit = slideOutVertically(targetOffsetY = { -it }) + fadeOut(),
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 80.dp)
        ) {
            tracking.guidanceReason?.let { reason ->
                GuidanceWarningBanner(
                    reason = reason,
                    // A field request: "when FC override happens, add a way
                    // to take control again in the app." Only offered while
                    // a continuous guidance mode is actually selected -
                    // there's nothing meaningful to resume for Idle/
                    // Tracking, and one-shot Grid Search already reverts
                    // its own button on rejection rather than staying
                    // "selected" waiting to be resumed.
                    onResume = if (mode in RESUMABLE_GUIDANCE_MODES) {
                        { viewModel.resumeGuidance() }
                    } else {
                        null
                    },
                )
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

/** Shown in place of live video whenever there's no remote track yet -
 * distinguishes "not connected, nothing to wait for" from "connected,
 * video negotiation still in progress" (a spinner - it should arrive
 * shortly) rather than a bare black rectangle either way. */
@Composable
private fun NoVideoPlaceholder(linkState: LinkState, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.background(Color.Black),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (linkState == LinkState.CONNECTED) {
                CircularProgressIndicator(
                    color = DroneColors.Accent,
                    modifier = Modifier.size(36.dp),
                )
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    "Waiting for video…",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                Text(
                    "No video",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    "Not connected to the aircraft",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
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
