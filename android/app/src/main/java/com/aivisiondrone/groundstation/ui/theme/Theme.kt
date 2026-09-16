package com.aivisiondrone.groundstation.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * A dark, glassy ground-control palette (DJI Fly / QGroundControl territory)
 * rather than stock Material defaults - the operator reads this outdoors,
 * often in direct sun, over live video, so contrast and a small set of
 * unambiguous status colors matter more than brand polish.
 */
object DroneColors {
    val Background = Color(0xFF0A0E13)
    val Surface = Color(0xFF141A22)
    val SurfaceElevated = Color(0xFF1C242F)
    val Accent = Color(0xFF00D9FF)
    val Safe = Color(0xFF30D158)
    val Warning = Color(0xFFFFD60A)
    val Danger = Color(0xFFFF453A)
    val TextPrimary = Color(0xFFF2F5F7)
    val TextSecondary = Color(0xFF8A96A3)
    val Overlay = Color(0xCC0A0E13)
}

private val DroneDarkScheme = darkColorScheme(
    primary = DroneColors.Accent,
    onPrimary = Color(0xFF00232A),
    secondary = DroneColors.Safe,
    background = DroneColors.Background,
    onBackground = DroneColors.TextPrimary,
    surface = DroneColors.Surface,
    onSurface = DroneColors.TextPrimary,
    surfaceVariant = DroneColors.SurfaceElevated,
    onSurfaceVariant = DroneColors.TextSecondary,
    error = DroneColors.Danger,
    onError = Color.White,
)

@Composable
fun DroneGroundStationTheme(content: @Composable () -> Unit) {
    // Always dark - a bright system theme fighting live video feels wrong
    // for a field tool, regardless of the phone's own day/night setting.
    val useDark = true
    val scheme = if (useDark) DroneDarkScheme else lightColorScheme()
    MaterialTheme(colorScheme = scheme, content = content)
}
