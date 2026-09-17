package com.aivisiondrone.groundstation.ui

import android.content.Context
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.control.AbortButton
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import com.aivisiondrone.groundstation.ui.tabs.AiModesTab
import com.aivisiondrone.groundstation.ui.tabs.ControlTab
import com.aivisiondrone.groundstation.ui.tabs.FlyTab
import com.aivisiondrone.groundstation.ui.tabs.SettingsTab
import org.webrtc.EglBase

/** Width above which we switch from a bottom nav bar to a side nav rail -
 * standard Material breakpoint for "the screen is wide enough that a
 * bottom bar wastes vertical space" (tablets, foldables opened flat). */
private val WIDE_SCREEN_BREAKPOINT = 600.dp

/**
 * Top-level ground-station layout: a DJI-Fly-style tabbed structure (Fly /
 * Control / AI Modes / Settings) instead of one crowded screen, with the
 * emergency abort button kept outside all tab content so it is reachable
 * no matter which tab is open (docs plan M6).
 */
@Composable
fun GroundStationScreen(viewModel: MainViewModel, eglBase: EglBase, context: Context) {
    val linkState by viewModel.linkState.collectAsState()
    val telemetry by viewModel.telemetry.collectAsState()
    val health by viewModel.health.collectAsState()
    val tracking by viewModel.tracking.collectAsState()
    val detections by viewModel.detections.collectAsState()
    val mode by viewModel.mode.collectAsState()
    val followSeparation by viewModel.followSeparationM.collectAsState()
    val followAltitude by viewModel.followAltitudeM.collectAsState()
    val orbitRadius by viewModel.orbitRadiusM.collectAsState()
    val orbitAltitude by viewModel.orbitAltitudeM.collectAsState()
    val remoteVideoTrack by viewModel.remoteVideoTrack.collectAsState()
    val recording by viewModel.recording.collectAsState()
    val showTargetActionSheet by viewModel.showTargetActionSheet.collectAsState()

    var selectedTab by remember { mutableStateOf(AppTab.FLY) }

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val isWideScreen = maxWidth >= WIDE_SCREEN_BREAKPOINT

        val content: @Composable (Modifier) -> Unit = { contentModifier ->
            when (selectedTab) {
                AppTab.FLY -> FlyTab(
                    viewModel = viewModel,
                    eglBase = eglBase,
                    context = context,
                    linkState = linkState,
                    telemetry = telemetry,
                    health = health,
                    tracking = tracking,
                    detections = detections,
                    mode = mode,
                    remoteVideoTrack = remoteVideoTrack,
                    showTargetActionSheet = showTargetActionSheet,
                    recording = recording,
                    onToggleRecording = { viewModel.toggleRecording() },
                    modifier = contentModifier,
                )
                AppTab.CONTROL -> ControlTab(
                    viewModel = viewModel,
                    telemetry = telemetry,
                    modifier = contentModifier,
                )
                AppTab.AI -> AiModesTab(
                    viewModel = viewModel,
                    mode = mode,
                    followSeparationM = followSeparation,
                    followAltitudeM = followAltitude,
                    orbitRadiusM = orbitRadius,
                    orbitAltitudeM = orbitAltitude,
                    tracking = tracking,
                    detections = detections,
                    modifier = contentModifier,
                )
                AppTab.SETTINGS -> SettingsTab(
                    viewModel = viewModel,
                    eglBase = eglBase,
                    context = context,
                    linkState = linkState,
                    modifier = contentModifier,
                )
            }
        }

        if (isWideScreen) {
            Row(modifier = Modifier.fillMaxSize()) {
                NavigationRail(containerColor = DroneColors.Surface) {
                    AppTab.entries.forEach { tab ->
                        NavigationRailItem(
                            selected = tab == selectedTab,
                            onClick = { selectedTab = tab },
                            icon = { Icon(tab.icon, contentDescription = tab.label) },
                            label = { Text(tab.label) },
                            colors = NavigationRailItemDefaults.colors(
                                selectedIconColor = DroneColors.Accent,
                                selectedTextColor = DroneColors.Accent,
                                unselectedIconColor = DroneColors.TextSecondary,
                                unselectedTextColor = DroneColors.TextSecondary,
                                indicatorColor = DroneColors.SurfaceElevated,
                            ),
                        )
                    }
                }
                Box(modifier = Modifier.fillMaxSize()) {
                    content(Modifier.fillMaxSize())
                    AbortButton(
                        onAbort = { viewModel.abort() },
                        modifier = Modifier.align(Alignment.BottomEnd),
                    )
                }
            }
        } else {
            Scaffold(
                bottomBar = {
                    NavigationBar(containerColor = DroneColors.Surface) {
                        AppTab.entries.forEach { tab ->
                            NavigationBarItem(
                                selected = tab == selectedTab,
                                onClick = { selectedTab = tab },
                                icon = { Icon(tab.icon, contentDescription = tab.label) },
                                label = { Text(tab.label) },
                                colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = DroneColors.Accent,
                                    selectedTextColor = DroneColors.Accent,
                                    unselectedIconColor = DroneColors.TextSecondary,
                                    unselectedTextColor = DroneColors.TextSecondary,
                                    indicatorColor = DroneColors.SurfaceElevated,
                                ),
                            )
                        }
                    }
                },
                containerColor = DroneColors.Background,
            ) { paddingValues ->
                Box(modifier = Modifier.padding(paddingValues).fillMaxSize()) {
                    content(Modifier.fillMaxSize())
                    AbortButton(
                        onAbort = { viewModel.abort() },
                        modifier = Modifier.align(Alignment.BottomEnd),
                    )
                }
            }
        }
    }
}
