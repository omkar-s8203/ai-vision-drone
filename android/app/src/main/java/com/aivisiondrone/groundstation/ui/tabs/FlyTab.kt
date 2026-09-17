package com.aivisiondrone.groundstation.ui.tabs

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import com.aivisiondrone.groundstation.control.DetectionsOverlay
import com.aivisiondrone.groundstation.control.DroneMode
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

        RecordButton(
            recording = recording.recording,
            durationS = recording.durationS,
            onClick = onToggleRecording,
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(16.dp),
        )

        tracking.guidanceReason?.let { reason ->
            GuidanceWarningBanner(
                reason = reason,
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(top = 64.dp),
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
                    .padding(bottom = 88.dp)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
            )
        }
    }
}
