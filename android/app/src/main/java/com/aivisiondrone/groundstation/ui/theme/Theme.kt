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
 * A premium, iOS-inspired dark palette. 
 * Uses deep blacks, translucent surfaces, and vibrant system accents.
 */
object DroneColors {
    val Background = Color(0xFF000000)
    val Surface = Color(0xFF111111)
    val SurfaceElevated = Color(0xFF222222)
    val Accent = Color(0xFF00C3FF) 
    val Safe = Color(0xFF34C759)   
    val Warning = Color(0xFFFFCC00) 
    val Danger = Color(0xFFFF3B30)  
    val TextPrimary = Color(0xFFFFFFFF)
    val TextSecondary = Color(0xFFAEAEB2) 
    val Overlay = Color(0xAA111111)
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
    primary = DroneColors.Accent,
    onPrimary = Color.White,
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
    MaterialTheme(
        colorScheme = DroneDarkScheme,
        typography = DroneTypography,
        content = content
    )
}
