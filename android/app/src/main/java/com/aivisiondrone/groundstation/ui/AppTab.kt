package com.aivisiondrone.groundstation.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FlightTakeoff
import androidx.compose.material.icons.filled.SettingsSuggest
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.ui.graphics.vector.ImageVector

/** Top-level ground-station sections, DJI-Fly-style: the live video/flight
 * view, direct FC control, AI guidance modes, and app/connection settings -
 * each its own tab rather than one crowded screen. */
enum class AppTab(val label: String, val icon: ImageVector) {
    FLY("Fly", Icons.Filled.Videocam),
    CONTROL("Control", Icons.Filled.FlightTakeoff),
    AI("AI Modes", Icons.Filled.SmartToy),
    SETTINGS("Settings", Icons.Filled.SettingsSuggest),
}
