package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
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
 */
@Composable
fun GuidanceWarningBanner(reason: String, modifier: Modifier = Modifier) {
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
        }
    }
}
