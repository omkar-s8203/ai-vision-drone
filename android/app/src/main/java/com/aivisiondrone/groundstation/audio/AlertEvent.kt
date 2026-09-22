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

    /** A field-reported bug ("I can't select Dronie/Parabola"): starting a
     * one-shot smart shot with no target actually locked (or one that just
     * went TARGET_LOST) gets silently refused by the Safety Supervisor -
     * the Pi's very next tracking_update already reports supervisorState
     * back at SAFE/IDLE with guidance_reason "target_lost", so
     * MainViewModel's own ONE_SHOT_MODES handling reverts the mode
     * selector to Normal RC within about one frame. From the operator's
     * side that looked exactly like "the button won't stay selected" with
     * no explanation - see MainViewModel.kt's TRACKING_UPDATE handling. */
    MODE_REJECTED_NO_TARGET("Can't start. No target locked"),

    /** Same silent-rejection gap as MODE_REJECTED_NO_TARGET, but for the
     * single most likely real-world cause of it: the Safety Supervisor
     * refuses EVERY guidance mode (Follow/Orbit/Approach/Dronie/Parabola/
     * Grid Search alike) whenever the flight controller isn't actually in
     * its designated AI-guidance mode (GUIDED - see main.py's
     * AI_GUIDANCE_MODE_NAME), completely independent of target tracking -
     * companion/safety/supervisor.py's fc_not_in_ai_mode check runs before
     * the target_lost check even gets a chance to matter. Until the FC is
     * actually switched to GUIDED (flight-mode dropdown, or the RC
     * transmitter), no guidance mode will ever engage, and without this
     * alert that looked identical to every other silent rejection. */
    MODE_REJECTED_FC_NOT_GUIDED("Can't start. Flight controller not in Guided mode"),

    /** Fallback for a guidance-mode rejection this app doesn't have a more
     * specific, worded alert for yet (comms_lost, obstacle_too_close) -
     * both already have their own more prominent indicators elsewhere
     * (the LINK status chip, the obstacle warning banner), so this exists
     * only so a future new rejection reason is never silently swallowed
     * again the way this whole class of bug originally was. */
    MODE_REJECTED("Guidance rejected"),
}
