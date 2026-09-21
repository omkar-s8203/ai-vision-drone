package com.aivisiondrone.groundstation.audio

/** A discrete, edge-triggered event derived from tracking/supervisor state
 * transitions (see MainViewModel's TRACKING_UPDATE/land-confirmation
 * handling) - each fires exactly once per transition, never once per frame,
 * so a beep/voice line plays once per real event instead of looping at the
 * telemetry frame rate. Consumed by AlertSoundPlayer. */
enum class AlertEvent(val spokenLine: String) {
    TARGET_LOCKED("Target locked"),
    TARGET_LOST("Target lost"),
    FOLLOWING_ENGAGED("Following target"),
    ORBITING_ENGAGED("Orbit engaged"),
    SEARCHING_STARTED("Searching for target"),
    RTL_TRIGGERED("Target not found. Returning home"),
    LAND_CONFIRMATION_NEEDED("Landing confirmation needed"),
    GUIDANCE_STOPPED("Guidance stopped. Pilot in control"),
    FENCE_BREACHED("Geofence breached"),

    /** A perimeter/intrusion zone the operator drew on the live video was
     * entered/cleared by a detection - a field request for a defence-
     * relevant feature: "perimeter / intrusion alert." See
     * MainViewModel.checkPerimeterIntrusion() and control/PerimeterZone.kt.
     * Edge-triggered on "any detection inside the zone" as a whole, not
     * per-object identity - general detections (unlike the one actively
     * tracked target) have no persistent ID to track individually across
     * frames. */
    PERIMETER_BREACHED("Perimeter breach detected"),
    PERIMETER_CLEARED("Perimeter clear"),

    /** Grid/lawnmower area-sweep search engaged (companion/guidance/
     * grid_search.py) - a real gap found in a code-review audit: every
     * other guidance mode (Follow/Orbit/Search) announces itself when
     * engaged, but Grid Search shipped with no case in
     * MainViewModel.emitTrackingAlerts()'s `when` block, so it silently
     * had no audio feedback at all despite otherwise following the exact
     * same supervisorState-transition pattern as the others. */
    GRID_SEARCH_STARTED("Grid search engaged"),
}
