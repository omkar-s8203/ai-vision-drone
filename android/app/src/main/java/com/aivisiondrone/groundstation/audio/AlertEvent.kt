package com.aivisiondrone.groundstation.audio

/** A discrete, edge-triggered event derived from tracking/supervisor state
 * transitions (see MainViewModel's TRACKING_UPDATE/land-confirmation
 * handling), plus one live-detection-driven case (ObjectDetected) - each
 * fires exactly once per transition/announcement, never once per frame,
 * so a beep/voice line plays once per real event instead of looping at the
 * telemetry frame rate. Consumed by AlertSoundPlayer.
 *
 * A sealed class rather than a plain enum specifically so ObjectDetected
 * can carry the detected class name and compute its own spoken line
 * ("Car detected", "Person detected", ...) instead of needing one fixed
 * case per possible COCO class - a field request: "if anything detect by
 * AI it should buzzer like Car detected, person detected." The other
 * cases keep their original (enum-style) names so every existing
 * `AlertEvent.TARGET_LOCKED`-style call site kept compiling unchanged.
 */
sealed class AlertEvent(val spokenLine: String) {
    object TARGET_LOCKED : AlertEvent("Target locked")
    object TARGET_LOST : AlertEvent("Target lost")
    object FOLLOWING_ENGAGED : AlertEvent("Following target")
    object ORBITING_ENGAGED : AlertEvent("Orbit engaged")
    object SEARCHING_STARTED : AlertEvent("Searching for target")
    object RTL_TRIGGERED : AlertEvent("Target not found. Returning home")
    object LAND_CONFIRMATION_NEEDED : AlertEvent("Landing confirmation needed")
    object GUIDANCE_STOPPED : AlertEvent("Guidance stopped. Pilot in control")
    object FENCE_BREACHED : AlertEvent("Geofence breached")

    /** `className` is COCO's raw label (already human-readable: person/
     * car/bicycle/...) - only raised for detections at/above the
     * announcement confidence threshold, debounced per class so the same
     * object doesn't get re-announced every single frame while it sits in
     * view (see MainViewModel.emitDetectionAnnouncements). */
    data class ObjectDetected(val className: String) :
        AlertEvent("${className.replaceFirstChar { c -> c.uppercase() }} detected")
}
