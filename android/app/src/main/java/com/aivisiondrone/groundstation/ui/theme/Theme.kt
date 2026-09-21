package com.aivisiondrone.groundstation.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/** One theme's worth of colors - the actual light/dark values live here,
 * `DroneColors` below just exposes whichever set is currently active. */
private class DronePalette(
    val background: Color,
    val surface: Color,
    val surfaceElevated: Color,
    val accent: Color,
    val safe: Color,
    val warning: Color,
    val danger: Color,
    val textPrimary: Color,
    val textSecondary: Color,
    val overlay: Color,
    val glass: Color,
)

private val DarkDronePalette = DronePalette(
    background = Color(0xFF000000),
    surface = Color(0xFF121212),
    surfaceElevated = Color(0xFF1E1E1E),
    accent = Color(0xFFFFCC00),
    safe = Color(0xFF34C759),
    warning = Color(0xFFFFCC00),
    danger = Color(0xFFFF3B30),
    textPrimary = Color(0xFFFFFFFF),
    textSecondary = Color(0xFFAEAEB2),
    overlay = Color(0xCC000000),
    glass = Color(0x661E1E1E),
)

// Light-mode equivalents - not just the dark palette's hues inverted:
// DarkDronePalette's brand yellow (#FFCC00) at full saturation reads as
// almost invisible against a white/light-gray surface (fails basic
// contrast), so light mode uses a darkened amber for Accent/Warning
// instead of the raw brand hue, same idea real iOS/Material light themes
// use for "this exact hue doesn't work on white" colors.
private val LightDronePalette = DronePalette(
    background = Color(0xFFF4F4F7),
    surface = Color(0xFFFFFFFF),
    surfaceElevated = Color(0xFFE8E8ED),
    accent = Color(0xFF9C6B00),
    safe = Color(0xFF1E8E3E),
    warning = Color(0xFF9C6B00),
    danger = Color(0xFFD93025),
    textPrimary = Color(0xFF1C1C1E),
    textSecondary = Color(0xFF6E6E73),
    overlay = Color(0x99000000),
    glass = Color(0x66FFFFFF),
)

// Backing state for DroneColors below - a plain (non-@Composable) global
// so every existing `DroneColors.X` call site keeps working unchanged,
// including the many non-composable helper functions across the app
// (e.g. StatusTab.kt's batteryColor()/gpsFixColor()) that would fail to
// compile if DroneColors' properties were declared `@Composable get()`
// instead. Compose's snapshot system still tracks reads of a
// mutableStateOf's .value regardless of whether the reading function
// itself is annotated @Composable, so recomposition on theme change still
// works correctly - only the call site inside an actual composable
// (which every real usage is, since these are all UI colors) needs to be
// in a composition, not the property getter itself.
private val currentDronePalette = mutableStateOf(DarkDronePalette)

/** Global color palette for the whole app - reflects whichever theme is
 * currently active (see DroneGroundStationTheme). Every property here was
 * a fixed dark-only value before; now it tracks the real dark/light
 * toggle (MainViewModel.isDarkMode), fixing light mode rendering
 * dark-styled cards on a light background. */
object DroneColors {
    val Background: Color get() = currentDronePalette.value.background
    val Surface: Color get() = currentDronePalette.value.surface
    val SurfaceElevated: Color get() = currentDronePalette.value.surfaceElevated
    val Accent: Color get() = currentDronePalette.value.accent
    val Safe: Color get() = currentDronePalette.value.safe
    val Warning: Color get() = currentDronePalette.value.warning
    val Danger: Color get() = currentDronePalette.value.danger
    val TextPrimary: Color get() = currentDronePalette.value.textPrimary
    val TextSecondary: Color get() = currentDronePalette.value.textSecondary
    val Overlay: Color get() = currentDronePalette.value.overlay
    val Glass: Color get() = currentDronePalette.value.glass
}

private val DroneTypography = Typography(
    headlineSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Bold,
        fontSize = 24.sp,
        letterSpacing = 0.sp
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 18.sp,
        letterSpacing = 0.sp
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        letterSpacing = 0.sp
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        letterSpacing = 0.5.sp
    )
)

private val DroneDarkScheme = darkColorScheme(
    primary = DarkDronePalette.accent,
    onPrimary = Color.Black,
    secondary = DarkDronePalette.safe,
    background = DarkDronePalette.background,
    onBackground = DarkDronePalette.textPrimary,
    surface = DarkDronePalette.surface,
    onSurface = DarkDronePalette.textPrimary,
    surfaceVariant = DarkDronePalette.surfaceElevated,
    onSurfaceVariant = DarkDronePalette.textSecondary,
    error = DarkDronePalette.danger,
    onError = Color.White,
)

private val DroneLightScheme = lightColorScheme(
    primary = LightDronePalette.accent,
    onPrimary = Color.White,
    secondary = LightDronePalette.safe,
    background = LightDronePalette.background,
    onBackground = LightDronePalette.textPrimary,
    surface = LightDronePalette.surface,
    onSurface = LightDronePalette.textPrimary,
    surfaceVariant = LightDronePalette.surfaceElevated,
    onSurfaceVariant = LightDronePalette.textSecondary,
    error = LightDronePalette.danger,
    onError = Color.White,
)

@Composable
fun DroneGroundStationTheme(darkTheme: Boolean = true, content: @Composable () -> Unit) {
    // Plain assignment (not a side-effect API) is deliberate: this must
    // land before `content()` below reads DroneColors while composing,
    // and it's idempotent (re-assigning the same palette on every
    // recomposition is harmless), so a LaunchedEffect's one-frame-later
    // timing would only add a visible flash of the wrong palette.
    currentDronePalette.value = if (darkTheme) DarkDronePalette else LightDronePalette
    val colorScheme = if (darkTheme) DroneDarkScheme else DroneLightScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = DroneTypography,
        content = content
    )
}
