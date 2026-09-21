package com.aivisiondrone.groundstation.ui

import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Flight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aivisiondrone.groundstation.R
import com.aivisiondrone.groundstation.MainViewModel
import com.aivisiondrone.groundstation.audio.AlertSoundPlayer
import com.aivisiondrone.groundstation.control.AbortButton
import com.aivisiondrone.groundstation.control.LandConfirmationDialog
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import com.aivisiondrone.groundstation.ui.tabs.AiModesTab
import com.aivisiondrone.groundstation.ui.tabs.ControlTab
import com.aivisiondrone.groundstation.ui.tabs.FlyTab
import com.aivisiondrone.groundstation.ui.tabs.SettingsTab
import com.aivisiondrone.groundstation.ui.tabs.StatusTab
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
    // Only state this composable's own body actually reads directly.
    // telemetry/health/tracking/detections/recording/remoteVideoTrack/mode/
    // etc. update on essentially every processed frame on the Pi and used
    // to be collected here, then threaded down as parameters - since
    // recomposition scope is the composable that reads the changed state,
    // that meant *this entire screen* (nav bar, abort button, tab switcher
    // included) recomposed 20-30 times a second no matter which tab was
    // open. Each tab now collects what it needs directly from `viewModel`
    // instead (see FlyTab.kt's docstring), confining that recomposition to
    // just the tab that's actually supposed to update that often.
    val landConfirmationRequest by viewModel.landConfirmationRequest.collectAsState()
    val alertsMuted by viewModel.alertsMuted.collectAsState()

    var selectedTab by remember { mutableStateOf(AppTab.FLY) }
    var menuVisible by remember { mutableStateOf(true) }

    // Buzzer + voice alerts for tracking/guidance state changes (target
    // locked/lost, follow/orbit engaged, RTL, etc.) - lives at this
    // top level, not inside a tab, so it keeps firing no matter which tab
    // is open, same reasoning as the abort button and land-confirmation
    // dialog below.
    val alertSoundPlayer = remember { AlertSoundPlayer(context) }
    DisposableEffect(Unit) {
        onDispose { alertSoundPlayer.release() }
    }
    LaunchedEffect(alertsMuted) {
        alertSoundPlayer.muted = alertsMuted
    }
    LaunchedEffect(Unit) {
        viewModel.alertEvents.collect { event -> alertSoundPlayer.play(event) }
    }

    // Rendered here (not inside a tab) so it's reachable no matter which
    // tab is open when target-loss recovery decides to ask, same
    // reasoning as the abort button below.
    landConfirmationRequest?.let { request ->
        LandConfirmationDialog(
            request = request,
            onApprove = { viewModel.respondToLandConfirmation(true) },
            onDeny = { viewModel.respondToLandConfirmation(false) },
        )
    }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        val isWideScreen = maxWidth >= WIDE_SCREEN_BREAKPOINT

        val content: @Composable (Modifier) -> Unit = { contentModifier ->
            Crossfade(
                targetState = selectedTab,
                animationSpec = tween(durationMillis = 300),
                modifier = contentModifier
            ) { tab ->
                when (tab) {
                    AppTab.FLY -> FlyTab(
                        viewModel = viewModel,
                        eglBase = eglBase,
                        context = context,
                    )
                    AppTab.CONTROL -> ControlTab(
                        viewModel = viewModel,
                    )
                    AppTab.AI -> AiModesTab(
                        viewModel = viewModel,
                    )
                    AppTab.STATUS -> StatusTab(
                        viewModel = viewModel,
                        alertsMuted = alertsMuted,
                        onSetAlertsMuted = { viewModel.setAlertsMuted(it) },
                    )
                    AppTab.SETTINGS -> SettingsTab(
                        viewModel = viewModel,
                        eglBase = eglBase,
                        context = context,
                    )
                }
            }
        }

        if (isWideScreen) {
            Row(modifier = Modifier.fillMaxSize()) {
                AnimatedVisibility(
                    visible = menuVisible,
                    enter = expandHorizontally(),
                    exit = shrinkHorizontally()
                ) {
                    NavigationRail(
                        containerColor = MaterialTheme.colorScheme.surface,
                        modifier = Modifier.width(84.dp),
                        header = {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier
                                    .statusBarsPadding()
                                    .padding(vertical = 12.dp)
                            ) {
                                // Stylized Brand Identity
                                Image(
                                    painter = painterResource(id = R.drawable.app_logo),
                                    contentDescription = "App Logo",
                                    modifier = Modifier
                                        .size(44.dp)
                                        .background(Color.Black, RoundedCornerShape(10.dp))
                                        .padding(4.dp)
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    "AI VISION",
                                    color = DroneColors.Accent,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Black,
                                    fontSize = 9.sp
                                )
                            }
                        }
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .verticalScroll(rememberScrollState()),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            AppTab.entries.forEach { tab ->
                                NavigationRailItem(
                                    selected = tab == selectedTab,
                                    onClick = { selectedTab = tab },
                                    icon = { Icon(tab.icon, contentDescription = tab.label, modifier = Modifier.size(22.dp)) },
                                    label = { Text(tab.label, style = MaterialTheme.typography.labelSmall, fontSize = 10.sp) },
                                    colors = NavigationRailItemDefaults.colors(
                                        selectedIconColor = DroneColors.Accent,
                                        selectedTextColor = DroneColors.Accent,
                                        unselectedIconColor = DroneColors.TextSecondary,
                                        unselectedTextColor = DroneColors.TextSecondary,
                                        indicatorColor = Color.Transparent,
                                    ),
                                )
                            }
                        }
                    }
                }
                
                Box(modifier = Modifier.fillMaxSize()) {
                    content(Modifier.fillMaxSize())
                    
                    // TOGGLE BUTTON (Wide Screen)
                    Box(
                        modifier = Modifier
                            .align(Alignment.CenterStart)
                            .padding(start = if (menuVisible) 0.dp else 8.dp)
                            .size(32.dp)
                            .background(DroneColors.Overlay, CircleShape)
                            .clickable { menuVisible = !menuVisible },
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = if (menuVisible) Icons.Filled.ChevronLeft else Icons.Filled.ChevronRight,
                            contentDescription = "Toggle Menu",
                            tint = Color.White,
                            modifier = Modifier.size(20.dp)
                        )
                    }

                    AbortButton(
                        onAbort = { viewModel.abort() },
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .padding(bottom = 20.dp, end = 20.dp),
                    )
                }
            }
        } else {
            Scaffold(
                bottomBar = {
                    AnimatedVisibility(
                        visible = menuVisible,
                        enter = expandVertically(),
                        exit = shrinkVertically()
                    ) {
                        NavigationBar(
                            containerColor = MaterialTheme.colorScheme.surface,
                            tonalElevation = 0.dp
                        ) {
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
                                        indicatorColor = Color.Transparent,
                                    ),
                                )
                            }
                        }
                    }
                },
                containerColor = MaterialTheme.colorScheme.background,
            ) { paddingValues ->
                Box(modifier = Modifier.padding(paddingValues).fillMaxSize()) {
                    content(Modifier.fillMaxSize())
                    
                    // TOGGLE BUTTON (Small Screen)
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .padding(bottom = if (menuVisible) 0.dp else 12.dp)
                            .size(40.dp, 24.dp)
                            .background(DroneColors.Overlay, RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp))
                            .clickable { menuVisible = !menuVisible },
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = if (menuVisible) Icons.Filled.ExpandMore else Icons.Filled.ExpandLess,
                            contentDescription = "Toggle Menu",
                            tint = Color.White,
                            modifier = Modifier.size(20.dp)
                        )
                    }

                    AbortButton(
                        onAbort = { viewModel.abort() },
                        modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp),
                    )
                }
            }
        }
    }
}
