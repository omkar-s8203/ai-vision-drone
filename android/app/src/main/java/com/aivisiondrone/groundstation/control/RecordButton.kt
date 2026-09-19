package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
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
import androidx.compose.ui.graphics.Color
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
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        IconButton(
            onClick = onClick,
            modifier = Modifier
                .size(size)
                .background(Color.White.copy(alpha = 0.1f), CircleShape)
                .padding(4.dp)
                .background(
                    if (recording) DroneColors.Danger else Color.White,
                    CircleShape,
                ),
        ) {
            Icon(
                imageVector = if (recording) Icons.Filled.Stop else Icons.Filled.FiberManualRecord,
                contentDescription = if (recording) "Stop recording" else "Start recording",
                tint = if (recording) Color.White else DroneColors.Danger,
                modifier = Modifier.size(if (recording) 24.dp else 28.dp)
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = if (recording) formatDuration(durationS) else "0:00",
            color = if (recording) DroneColors.Danger else Color.White,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
            modifier = Modifier
                .background(DroneColors.Overlay, RoundedCornerShape(4.dp))
                .padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
