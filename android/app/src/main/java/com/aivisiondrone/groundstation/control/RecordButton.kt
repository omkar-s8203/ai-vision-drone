package com.aivisiondrone.groundstation.control

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

private fun formatDuration(seconds: Double): String {
    val total = seconds.toInt().coerceAtLeast(0)
    val m = total / 60
    val s = total % 60
    return "%d:%02d".format(m, s)
}

/**
 * Local video-record toggle - separate from the WebRTC feed, so footage is
 * captured on the Pi's own storage regardless of link quality. Lives on the
 * main Fly screen (not tucked into a settings/control tab) since that's
 * where the operator is actually looking while filming, matching DJI's
 * shutter/record button placement directly on the camera view.
 */
@Composable
fun RecordButton(
    recording: Boolean,
    durationS: Double,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 56.dp,
) {
    val transition = rememberInfiniteTransition(label = "record-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label = "record-pulse-alpha",
    )

    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        IconButton(
            onClick = onClick,
            modifier = Modifier
                .size(size)
                .background(
                    if (recording) DroneColors.Danger.copy(alpha = 0.18f) else DroneColors.SurfaceElevated,
                    CircleShape,
                ),
        ) {
            Icon(
                imageVector = if (recording) Icons.Filled.Stop else Icons.Filled.FiberManualRecord,
                contentDescription = if (recording) "Stop recording" else "Start recording",
                tint = if (recording) DroneColors.Danger.copy(alpha = pulse) else DroneColors.TextPrimary,
            )
        }
        Text(
            text = if (recording) formatDuration(durationS) else "REC",
            color = if (recording) DroneColors.Danger else DroneColors.TextSecondary,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier
                .padding(top = 2.dp)
                .background(DroneColors.Overlay, RoundedCornerShape(6.dp))
                .padding(horizontal = 6.dp, vertical = 1.dp),
        )
    }
}
