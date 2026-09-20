package com.aivisiondrone.groundstation.ui.tabs

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.telemetry.HealthState
import com.aivisiondrone.groundstation.telemetry.TelemetryState
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import kotlin.math.cos
import kotlin.math.sin

/**
 * A full MAVLink telemetry dashboard - QGroundControl-style grouped status
 * cards (Vehicle/Position/GPS/Attitude/Navigation/Battery/RC Input/Health)
 * plus a live home-direction radar. Every value here is real data already
 * flowing over the `telemetry`/`health` messages (docs/protocol.md) - a
 * card with no backing MAVLink source (mission upload, ADS-B) is left out
 * entirely rather than shown permanently empty, since this app has neither
 * feature.
 */
@Composable
fun StatusTab(
    telemetry: TelemetryState,
    health: HealthState,
    alertsMuted: Boolean,
    onSetAlertsMuted: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            "Status",
            color = DroneColors.TextPrimary,
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(start = 4.dp),
        )

        CardRow {
            StatusCard("VEHICLE", Modifier.weight(1f)) {
                StatusRow("Armed", if (telemetry.armed) "ARMED" else "DISARMED", if (telemetry.armed) DroneColors.Danger else DroneColors.TextSecondary)
                StatusRow("Mode", telemetry.flightMode ?: "--")
                StatusRow("Link", if (health.mavlinkOk) "OK" else "NO LINK", if (health.mavlinkOk) DroneColors.Safe else DroneColors.Danger)
                StatusRow("Autopilot", "ArduCopter")
            }
            StatusCard("POSITION", Modifier.weight(1f)) {
                StatusRow("Lat", fmtCoord(telemetry.lat))
                StatusRow("Lon", fmtCoord(telemetry.lon))
                StatusRow("Rel alt", fmt(telemetry.altitudeM, 1, " m"))
                StatusRow("Home", if (telemetry.homeLat != null) "${fmtCoord(telemetry.homeLat)}, ${fmtCoord(telemetry.homeLon)}" else "not set")
                StatusRow("Home dist", fmt(telemetry.distanceToHomeM, 0, " m"))
            }
        }

        CardRow {
            StatusCard("GPS", Modifier.weight(1f)) {
                StatusRow("Fix", gpsFixLabel(telemetry.gpsFixType), gpsFixColor(telemetry.gpsFixType))
                StatusRow("Satellites", telemetry.satellitesVisible?.toString() ?: "--")
                StatusRow("HDOP", fmt(telemetry.hdop, 2))
                StatusRow("VDOP", fmt(telemetry.vdop, 2))
            }
            StatusCard("ATTITUDE", Modifier.weight(1f)) {
                StatusRow("Roll", fmt(telemetry.rollDeg, 1, "°"))
                StatusRow("Pitch", fmt(telemetry.pitchDeg, 1, "°"))
                StatusRow("Yaw", fmt(telemetry.yawDeg, 1, "°"))
            }
        }

        CardRow {
            StatusCard("NAVIGATION", Modifier.weight(1f)) {
                StatusRow("Heading", fmt(telemetry.headingDeg, 0, "°"))
                StatusRow("Ground spd", fmt(telemetry.groundspeedMps, 1, " m/s"))
                StatusRow("Air spd", fmt(telemetry.airspeedMps, 1, " m/s"))
                StatusRow("Climb", fmt(telemetry.climbMps, 1, " m/s"))
                StatusRow("Throttle", telemetry.throttlePct?.let { "$it%" } ?: "--")
            }
            StatusCard("BATTERY", Modifier.weight(1f)) {
                StatusRow("Voltage", fmt(telemetry.batteryVoltage, 2, " V"))
                StatusRow("Remaining", telemetry.batteryRemainingPct?.let { "$it%" } ?: "--", batteryColor(telemetry.batteryRemainingPct))
                StatusRow("Current", fmt(telemetry.currentBatteryA, 1, " A"))
            }
        }

        CardRow {
            StatusCard("RC INPUT", Modifier.weight(1f)) {
                val hasRc = telemetry.rcRssiPct != null
                StatusRow("Status", if (hasRc) "OK" else "NO INPUT", if (hasRc) DroneColors.Safe else DroneColors.Warning)
                StatusRow("RSSI", telemetry.rcRssiPct?.let { "$it%" } ?: "--")
            }
            StatusCard("HEALTH", Modifier.weight(1f)) {
                StatusRow("Pi / Camera", "${onOff(health.piOk)} / ${onOff(health.cameraOk)}")
                StatusRow("AI / Tracker", "${onOff(health.aiOk)} / ${onOff(health.trackerOk)}")
                StatusRow("Video", onOff(health.videoOk))
                StatusRow("FPS", fmt(health.fps, 0))
            }
        }

        Card(
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    "HOME RADAR",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.fillMaxWidth(),
                )
                HomeRadar(
                    headingDeg = telemetry.headingDeg,
                    homeBearingDeg = telemetry.homeBearingDeg,
                    modifier = Modifier
                        .padding(vertical = 12.dp)
                        .size(200.dp),
                )
                Text(
                    if (telemetry.distanceToHomeM != null) "${"%.0f".format(telemetry.distanceToHomeM)} m to home"
                    else "Home not set yet",
                    color = DroneColors.TextPrimary,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Yellow = nose heading   ·   Red = direction to home",
                    color = DroneColors.TextSecondary,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        }

        Card(
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text("Buzzer & voice alerts", color = DroneColors.TextPrimary, style = MaterialTheme.typography.bodyMedium)
                    Text(
                        "Target locked/lost, follow/orbit engaged, RTL, and more",
                        color = DroneColors.TextSecondary,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
                Switch(
                    checked = !alertsMuted,
                    onCheckedChange = { onSetAlertsMuted(!it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = DroneColors.Accent),
                )
            }
        }
    }
}

@Composable
private fun CardRow(content: @Composable RowScope.() -> Unit) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        content()
    }
}

@Composable
private fun StatusCard(title: String, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Card(
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Surface),
        modifier = modifier,
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                title,
                color = DroneColors.TextSecondary,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(bottom = 6.dp),
            )
            content()
        }
    }
}

@Composable
private fun StatusRow(label: String, value: String, valueColor: Color = DroneColors.TextPrimary) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = DroneColors.TextSecondary, style = MaterialTheme.typography.labelSmall)
        Text(value, color = valueColor, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium)
    }
}

/** A live compass: a fixed north-up ring, a cyan line for the aircraft's
 * own heading (VFR_HUD), and a red needle for the real computed bearing
 * toward home (companion/guidance/geo.py) - the same "which way is home"
 * instrument DJI's own app shows, built from real telemetry rather than a
 * static graphic. */
@Composable
private fun HomeRadar(headingDeg: Double?, homeBearingDeg: Double?, modifier: Modifier = Modifier) {
    Canvas(modifier = modifier.aspectRatio(1f)) {
        val radius = size.minDimension / 2f * 0.82f
        val center = Offset(size.width / 2f, size.height / 2f)
        val strokeWidth = 2.dp.toPx()

        drawCircle(color = DroneColors.SurfaceElevated, radius = radius, center = center, style = Stroke(width = strokeWidth))
        drawCircle(color = DroneColors.SurfaceElevated, radius = radius * 0.6f, center = center, style = Stroke(width = strokeWidth * 0.6f))

        for (angle in 0 until 360 step 30) {
            val rad = Math.toRadians(angle - 90.0)
            val inner = if (angle % 90 == 0) radius * 0.85f else radius * 0.92f
            val start = Offset(center.x + inner * cos(rad).toFloat(), center.y + inner * sin(rad).toFloat())
            val end = Offset(center.x + radius * cos(rad).toFloat(), center.y + radius * sin(rad).toFloat())
            drawLine(DroneColors.TextSecondary, start, end, strokeWidth = strokeWidth)
        }

        if (headingDeg != null) {
            val rad = Math.toRadians(headingDeg - 90.0)
            val tip = Offset(center.x + radius * 0.55f * cos(rad).toFloat(), center.y + radius * 0.55f * sin(rad).toFloat())
            drawLine(DroneColors.Accent, center, tip, strokeWidth = strokeWidth * 2.5f)
            drawCircle(DroneColors.Accent, radius = 5.dp.toPx(), center = tip)
        }

        if (homeBearingDeg != null) {
            val rad = Math.toRadians(homeBearingDeg - 90.0)
            val tip = Offset(center.x + radius * cos(rad).toFloat(), center.y + radius * sin(rad).toFloat())
            drawLine(DroneColors.Danger, center, tip, strokeWidth = strokeWidth * 2)
            drawCircle(DroneColors.Danger, radius = 6.dp.toPx(), center = tip)
        }

        drawCircle(DroneColors.TextPrimary, radius = 4.dp.toPx(), center = center)
    }
}

private fun fmt(v: Double?, decimals: Int, suffix: String = ""): String =
    v?.let { "%.${decimals}f".format(it) + suffix } ?: "--"

private fun fmtCoord(v: Double?): String = v?.let { "%.6f".format(it) } ?: "--"

private fun onOff(ok: Boolean): String = if (ok) "OK" else "--"

private fun gpsFixLabel(fixType: Int?): String = when (fixType) {
    null -> "--"
    0, 1 -> "NO FIX"
    2 -> "2D FIX"
    3 -> "3D FIX"
    4 -> "DGPS"
    5 -> "RTK FLOAT"
    6 -> "RTK FIXED"
    else -> "3D+"
}

private fun gpsFixColor(fixType: Int?) = when {
    fixType == null || fixType <= 1 -> DroneColors.Danger
    fixType == 2 -> DroneColors.Warning
    else -> DroneColors.Safe
}

private fun batteryColor(pct: Int?) = when {
    pct == null -> DroneColors.TextPrimary
    pct < 20 -> DroneColors.Danger
    pct < 40 -> DroneColors.Warning
    else -> DroneColors.Safe
}
