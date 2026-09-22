package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/** guidance_reason codes where the block is expected to clear on its own
 * once the real condition does (the pilot releases the sticks / switches
 * back to GUIDED) - a "Resume" tap here can never bypass that real gate
 * (the Pi re-evaluates it fresh every frame independent of what the app
 * sends), it only resends the already-selected mode as a deliberate,
 * visible action instead of the operator silently waiting. Every other
 * reason (an obstacle, comms loss, a stale subsystem, target loss) isn't
 * something re-sending the same mode command can do anything about. */
private val RESUMABLE_REASONS = setOf("rc_override", "fc_not_in_ai_mode")

/** Human-readable labels for the Safety Supervisor's `guidance_reason`
 * codes (companion/safety/supervisor.py) - shown to the operator instead
 * of the raw wire string. Falls back to the raw code for anything new. */
private fun describeReason(reason: String): String = when {
    reason.startsWith("obstacle_too_close") -> {
        // "obstacle_too_close:<class_name>:<distance_m>m"
        val parts = reason.split(":")
        val className = parts.getOrNull(1) ?: "object"
        val distance = parts.getOrNull(2) ?: ""
        "Obstacle too close: $className at $distance"
    }
    reason.startsWith("stale_subsystems") -> "System check failed - guidance paused"
    reason == "rc_override" -> "RC override active - AI guidance paused"
    reason == "comms_lost" -> "Ground station link lost - guidance paused"
    reason == "fc_not_in_ai_mode" -> "Flight controller not in AI guidance mode"
    reason == "target_lost" -> "Target lost - guidance paused"
    else -> reason
}

/**
 * Surfaces the Safety Supervisor's reason for blocking guidance - this was
 * previously parsed into TrackingState.guidanceReason but never actually
 * shown anywhere, so an operator had no visible explanation when the drone
 * silently stopped following/orbiting (e.g. an obstacle proximity trip).
 *
 * `onResume`, when provided, renders a "Resume" button for a field request
 * ("when FC override happens, add a way to take control again in the
 * app") - only meaningful (and only ever passed) for reasons in
 * RESUMABLE_REASONS; the caller (FlyTab.kt) is responsible for that check
 * and for only passing it when a continuous guidance mode is actually
 * selected, since there's nothing to resume otherwise.
 */
@Composable
fun GuidanceWarningBanner(reason: String, onResume: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    val isObstacle = reason.startsWith("obstacle_too_close")
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = (if (isObstacle) DroneColors.Danger else DroneColors.Warning).copy(alpha = 0.92f),
        ),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Warning, contentDescription = null, tint = DroneColors.Background)
            Text(
                text = describeReason(reason),
                color = DroneColors.Background,
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(start = 8.dp),
            )
            if (onResume != null && reason in RESUMABLE_REASONS) {
                Spacer(modifier = Modifier.width(12.dp))
                Button(
                    onClick = onResume,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = DroneColors.Background,
                        contentColor = DroneColors.TextPrimary,
                    ),
                ) {
                    Text("Resume")
                }
            }
        }
    }
}
