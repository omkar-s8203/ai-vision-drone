package com.aivisiondrone.groundstation

import android.content.pm.ActivityInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import com.aivisiondrone.groundstation.ui.GroundStationScreen
import com.aivisiondrone.groundstation.ui.theme.DroneGroundStationTheme
import org.webrtc.EglBase

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()
    private lateinit var eglBase: EglBase

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        eglBase = EglBase.create()

        setContent {
            DroneGroundStationTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val eglBaseState = remember { eglBase }
                    GroundStationScreen(
                        viewModel = viewModel,
                        eglBase = eglBaseState,
                        context = this,
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        eglBase.release()
    }
}
