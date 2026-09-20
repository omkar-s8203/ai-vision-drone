package com.aivisiondrone.groundstation.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * A standard, high-contrast dark and light palette matching the AI Vision Drone brand.
 */
object DroneColors {
    val Accent = Color(0xFFFFCC00) // Brand Yellow
    val Safe = Color(0xFF34C759)   
    val Warning = Color(0xFFFFCC00) 
    val Danger = Color(0xFFFF3B30)  
    val Overlay = Color(0xCC000000)
    val Glass = Color(0x661E1E1E)

    // Explicit dark theme default colors to prevent non-composable invocation errors
    val Background = Color(0xFF000000)
    val Surface = Color(0xFF121212)
    val SurfaceElevated = Color(0xFF1E1E1E)
    val TextPrimary = Color(0xFFFFFFFF)
    val TextSecondary = Color(0xFFAEAEB2)
}

// Composable function mappings for responsive themes
@Composable
fun droneBackground() = MaterialTheme.colorScheme.background

@Composable
fun droneSurface() = MaterialTheme.colorScheme.surface

@Composable
fun droneSurfaceElevated() = MaterialTheme.colorScheme.surfaceVariant

@Composable
fun droneTextPrimary() = MaterialTheme.colorScheme.onSurface

@Composable
fun droneTextSecondary() = MaterialTheme.colorScheme.onSurfaceVariant

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
    primary = DroneColors.Accent,
    onPrimary = Color.Black,
    secondary = DroneColors.Safe,
    background = Color(0xFF000000),
    onBackground = Color(0xFFFFFFFF),
    surface = Color(0xFF121212),
    onSurface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFF1E1E1E),
    onSurfaceVariant = Color(0xFFAEAEB2),
    error = DroneColors.Danger,
    onError = Color.White,
)

private val DroneLightScheme = lightColorScheme(
    primary = DroneColors.Accent,
    onPrimary = Color.Black,
    secondary = DroneColors.Safe,
    background = Color(0xFFF4F4F7),
    onBackground = Color(0xFF1C1C1E),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF1C1C1E),
    surfaceVariant = Color(0xFFE5E5EA),
    onSurfaceVariant = Color(0xFF8E8E93),
    error = DroneColors.Danger,
    onError = Color.White,
)

@Composable
fun DroneGroundStationTheme(darkTheme: Boolean = true, content: @Composable () -> Unit) {
    val colorScheme = if (darkTheme) DroneDarkScheme else DroneLightScheme
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = DroneTypography,
        content = content
    )
}
