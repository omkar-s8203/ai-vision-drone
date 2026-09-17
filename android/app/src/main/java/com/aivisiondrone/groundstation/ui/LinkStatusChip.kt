package com.aivisiondrone.groundstation.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aivisiondrone.groundstation.comms.LinkState
import com.aivisiondrone.groundstation.ui.theme.DroneColors

@Composable
fun LinkStatusChip(linkState: LinkState, modifier: Modifier = Modifier) {
    val color = when (linkState) {
        LinkState.CONNECTED -> DroneColors.Safe
        LinkState.CONNECTING -> DroneColors.Warning
        LinkState.DISCONNECTED -> DroneColors.Danger
    }
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = DroneColors.Overlay),
    ) {
        Text(
            text = "LINK: ${linkState.name}",
            color = color,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
