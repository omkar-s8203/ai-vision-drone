package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.telemetry.TrackingState
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * Shows the active guidance controller's computed velocity setpoint live -
 * previously this only ever reached the Pi's own session log file
 * (companion/main.py's SessionRecorder), reviewable only after the fact.
 * The plan's own staged real-flight procedure explicitly calls for a
 * props-off bench dry-run "watching commanded velocities on a dashboard
 * before ever arming" - this panel is that dashboard. Only rendered while
 * a guidance controller is actually producing a command, so it doesn't
 * clutter the screen the rest of the time (Tracking-only, Normal RC, etc).
 */
@Composable
fun GuidanceCommandPanel(tracking: TrackingState, modifier: Modifier = Modifier) {
    if (tracking.commandedVxMps == null) return

    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Overlay),
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Text(
                text = if (tracking.guidanceSent) "GUIDANCE SENT" else "GUIDANCE BLOCKED",
                color = if (tracking.guidanceSent) DroneColors.Safe else DroneColors.Warning,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "vx: %.2f  vy: %.2f  vz: %.2f m/s".format(
                    tracking.commandedVxMps,
                    tracking.commandedVyMps ?: 0.0,
                    tracking.commandedVzMps ?: 0.0,
                ),
                color = DroneColors.TextPrimary,
                style = MaterialTheme.typography.labelSmall,
            )
            Text(
                "yaw rate: %.2f rad/s".format(tracking.commandedYawRateRads ?: 0.0),
                color = DroneColors.TextPrimary,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
