package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aivisiondrone.groundstation.ui.theme.DroneColors

/**
 * Always-reachable emergency stop - per docs plan M6, this must never be
 * nested behind other UI. Every screen that hosts the main layout should
 * place this in the same fixed position.
 */
@Composable
fun AbortButton(onAbort: () -> Unit, modifier: Modifier = Modifier) {
    Button(
        onClick = onAbort,
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = DroneColors.Danger,
            contentColor = Color.White
        ),
        elevation = ButtonDefaults.buttonElevation(defaultElevation = 6.dp),
        modifier = modifier
            .height(44.dp)
            .width(120.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp)
    ) {
        Icon(
            Icons.Filled.Warning, 
            contentDescription = null, 
            tint = Color.White,
            modifier = Modifier.size(16.dp)
        )
        Text(
            "ABORT",
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Black,
            letterSpacing = 1.sp,
            modifier = Modifier.padding(start = 8.dp),
        )
    }
}
