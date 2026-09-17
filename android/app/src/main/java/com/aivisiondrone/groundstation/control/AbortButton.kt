package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Always-reachable emergency stop - per docs plan M6, this must never be
 * nested behind other UI. Every screen that hosts the main layout should
 * place this in the same fixed position.
 */
@Composable
fun AbortButton(onAbort: () -> Unit, modifier: Modifier = Modifier) {
    Button(
        onClick = onAbort,
        shape = RoundedCornerShape(28.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD32F2F)),
        modifier = modifier.padding(8.dp),
    ) {
        Icon(Icons.Filled.Warning, contentDescription = null, tint = Color.White)
        Text(
            "STOP / ABORT",
            style = MaterialTheme.typography.titleMedium,
            color = Color.White,
            modifier = Modifier.padding(start = 6.dp),
        )
    }
}
