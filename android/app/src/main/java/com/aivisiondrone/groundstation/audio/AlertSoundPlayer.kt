package com.aivisiondrone.groundstation.audio

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.speech.tts.TextToSpeech
import android.util.Log
import java.util.Locale

/** Hands-free audio feedback for tracking/guidance state changes - a beep
 * (ToneGenerator, plays instantly, no engine warm-up) immediately followed
 * by a short spoken line (TextToSpeech) so an operator whose eyes are on
 * the aircraft, not the phone, still knows what it just did without having
 * to glance at the screen. Both use STREAM_MUSIC, the same stream the
 * WebRTC video audio uses, so one volume control covers everything. */
class AlertSoundPlayer(context: Context) {
    private val toneGenerator: ToneGenerator? = try {
        ToneGenerator(AudioManager.STREAM_MUSIC, MAX_TONE_VOLUME)
    } catch (e: RuntimeException) {
        Log.w(TAG, "ToneGenerator unavailable on this device", e)
        null
    }

    private var ttsReady = false
    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        ttsReady = status == TextToSpeech.SUCCESS
    }

    var muted: Boolean = false

    fun play(event: AlertEvent) {
        if (muted) return
        toneGenerator?.startTone(toneFor(event), TONE_DURATION_MS)
        if (ttsReady) {
            tts.language = Locale.US
            tts.speak(event.spokenLine, TextToSpeech.QUEUE_ADD, null, event.name)
        }
    }

    /** Immediately silences any speech in progress and discards everything
     * queued behind it - a real field-reported bug: hitting Abort mid a
     * failsafe cascade (e.g. "Target lost" -> "Searching" -> "Returning
     * home" queued up in the seconds before the operator reacted) used to
     * keep talking for several more seconds after the abort itself had
     * already taken effect, since nothing ever told the TTS queue to
     * clear. `TextToSpeech.stop()` does exactly that: stops the current
     * utterance and drops the queue, without needing a full
     * stop()+shutdown()+recreate cycle. */
    fun stopAll() {
        tts.stop()
    }

    fun release() {
        toneGenerator?.release()
        tts.stop()
        tts.shutdown()
    }

    private fun toneFor(event: AlertEvent): Int = when (event) {
        AlertEvent.TARGET_LOCKED -> ToneGenerator.TONE_PROP_ACK
        AlertEvent.FOLLOWING_ENGAGED -> ToneGenerator.TONE_PROP_BEEP2
        AlertEvent.ORBITING_ENGAGED -> ToneGenerator.TONE_PROP_BEEP2
        AlertEvent.SEARCHING_STARTED -> ToneGenerator.TONE_PROP_BEEP
        AlertEvent.TARGET_LOST -> ToneGenerator.TONE_CDMA_ABBR_ALERT
        AlertEvent.RTL_TRIGGERED -> ToneGenerator.TONE_CDMA_ABBR_ALERT
        AlertEvent.LAND_CONFIRMATION_NEEDED -> ToneGenerator.TONE_CDMA_ABBR_ALERT
        AlertEvent.GUIDANCE_STOPPED -> ToneGenerator.TONE_SUP_ERROR
        AlertEvent.FENCE_BREACHED -> ToneGenerator.TONE_SUP_ERROR
        AlertEvent.PERIMETER_BREACHED -> ToneGenerator.TONE_CDMA_ABBR_ALERT
        AlertEvent.PERIMETER_CLEARED -> ToneGenerator.TONE_PROP_ACK
    }

    companion object {
        private const val TAG = "AlertSoundPlayer"
        private const val MAX_TONE_VOLUME = 100
        private const val TONE_DURATION_MS = 200
    }
}
