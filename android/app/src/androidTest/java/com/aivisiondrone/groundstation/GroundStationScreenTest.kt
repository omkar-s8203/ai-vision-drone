package com.aivisiondrone.groundstation

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipe
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Per docs plan M6: "Espresso UI tests for target-selection gesture and
 * STOP button reachability from every screen state." No live Pi connection
 * is established here - these assert UI structure and gesture handling
 * don't crash, not the resulting network messages (that's covered on the
 * Pi side by companion/tests/test_mode_command.py etc.).
 */
@RunWith(AndroidJUnit4::class)
class GroundStationScreenTest {

    @get:Rule
    val composeTestRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun abortButtonIsReachableOnLaunch() {
        composeTestRule.onNodeWithText("STOP / ABORT").assertExists()
    }

    @Test
    fun modeControlsAreVisibleOnLaunch() {
        composeTestRule.onNodeWithText("Normal RC").assertExists()
        composeTestRule.onNodeWithText("Tracking").assertExists()
        composeTestRule.onNodeWithText("Follow").assertExists()
        composeTestRule.onNodeWithText("Approach Test").assertExists()
    }

    @Test
    fun abortButtonRemainsReachableAfterModeSwitch() {
        // Switching modes must never hide or remove the abort control -
        // it's the one thing that must always be reachable.
        composeTestRule.onNodeWithText("Follow").performClick()
        composeTestRule.onNodeWithText("STOP / ABORT").assertExists()
    }

    @Test
    fun dragGestureOnVideoAreaDoesNotCrash() {
        composeTestRule.onRoot().performTouchInput {
            swipe(start = Offset(100f, 100f), end = Offset(300f, 300f))
        }
        composeTestRule.onNodeWithText("STOP / ABORT").assertExists()
    }
}
