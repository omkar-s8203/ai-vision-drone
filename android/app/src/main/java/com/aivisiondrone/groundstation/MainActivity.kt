package com.aivisiondrone.groundstation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import com.aivisiondrone.groundstation.ui.GroundStationScreen
import org.webrtc.EglBase

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()
    private lateinit var eglBase: EglBase

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        eglBase = EglBase.create()

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier) {
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
