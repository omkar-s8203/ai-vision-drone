# Android Ground Station

Native Kotlin, Jetpack Compose, single-activity app (docs plan M6). Talks to
the Pi's `companion/comms` layer: a WebSocket control/telemetry channel and
a separate WebRTC video channel, per `docs/protocol.md`.

## Status

**Builds, runs, and works end-to-end** - confirmed live on a real device
against the Pi's sim companion stack over real WiFi (connects, streams
synthetic video, drag-to-select correctly initializes tracking, tracking
overlay updates live), and now also confirmed against the **real hardware
companion session** (real camera, real on-sensor AI detection, real
MAVLink-backed Pi): connect, live video, and drag/tap target selection
with the tracking overlay all working end-to-end on a physical phone.
Arm/disarm, the flight-mode dropdown, the guidance-mode buttons, the
record-video toggle, and the obstacle-warning banner are still only
build-verified, not yet exercised against either a live sim or hardware
session. This project's dev environment has no Android SDK, so every fix
below came from you pasting back a real build/runtime error - that's the
expected way this gets verified from here on out.

Fixed so far:
- **Kotlin/Compose plugin version mismatch**: `org.jetbrains.kotlin.plugin.compose`
  only exists from Kotlin 2.0.0 onward. Bumped `org.jetbrains.kotlin.android`
  and `org.jetbrains.kotlin.plugin.compose` to 2.0.21 together.
- **Invalid `spacedBy` import** in `ModeControls.kt` and `HealthPanel.kt` -
  `Arrangement.spacedBy` is a member of `Arrangement`, not a top-level
  function; fixed to import `Arrangement` and call it properly.
- **16 KB page-size alignment warning** - `stream-webrtc-android:1.1.1` and
  a transitive `androidx.graphics:graphics-path` were both built before
  Google's 16 KB native-library alignment requirement. Bumped
  `stream-webrtc-android` to 1.3.10, pinned `graphics-path` to 1.1.0
  explicitly, bumped the Compose BOM to 2025.12.01, and dropped 32-bit ABIs
  (`armeabi-v7a`/`x86`) since a phone/tablet ground station only needs
  arm64 - GetStream's own alignment fixes reportedly lagged for 32-bit for
  a while, so this sidesteps that entirely rather than chasing it further.
- **AAR metadata errors from the Compose BOM bump** - Compose 1.10.0 (pulled
  in by the BOM bump above) requires `compileSdk 35` and AGP `>= 8.6.0`,
  but the project was on `compileSdk 34` / AGP 8.5.2. Bumped AGP to 8.9.0
  (supports up to API 35, needs Gradle >= 8.11.1 - wrapper updated to
  match), and `compileSdk` to 35. `targetSdk` deliberately left at 34 for
  now - that's a separate, larger decision (new runtime behavior opt-in)
  from just compiling against newer APIs.
- **`Unresolved reference 'ExposedDropdownMenu'`** in `FlightControlDock.kt`
  - `ExposedDropdownMenu` is a member function of Material3's
  `ExposedDropdownMenuBoxScope`, not a top-level composable, so importing it
  from `androidx.compose.material3` fails. The call site inside
  `ExposedDropdownMenuBox`'s content lambda already resolves it correctly
  via the implicit receiver - the fix was simply deleting the bad import.
- **Missing `TrackingState` import** in `TrackingOverlay.kt` after adding
  the orbit-ring feature - a real `Unresolved reference 'TrackingState'`
  (plus a cascade of ~20 follow-on errors on every field access) caught by
  a real Gradle build.
- **`Could not find androidx.compose.ui:ui-test-junit4:` (blank version)**
  when building the androidTest APK - the Compose BOM
  (`platform("androidx.compose:compose-bom:...")`) was only applied to the
  main `implementation` configuration; `androidTestImplementation` needs
  its own `platform(...)` line or version-less Compose test artifacts have
  no version to resolve against. Fixed by adding the BOM to
  `androidTestImplementation` too.
- **`Unresolved reference 'assertExists'`** in `GroundStationScreenTest.kt`,
  even after the BOM fix above and with sibling test functions
  (`onNodeWithText`, `performClick`, etc.) compiling fine - confirmed by
  extracting and grepping the actual resolved `ui-test` jar's bytecode
  (`SemanticsNodeInteraction.class`) that `assertExists()`/
  `assertDoesNotExist()` are member methods on `SemanticsNodeInteraction`
  in this Compose version, not top-level extension functions in
  `AssertionsKt` anymore - the `.assertExists()` call sites were always
  fine, the now-invalid `import androidx.compose.ui.test.assertExists`
  line was the only problem. Also added an explicit
  `androidTestImplementation("androidx.compose.ui:ui-test")` alongside
  `ui-test-junit4` while investigating, since it shouldn't be assumed to
  always arrive transitively.

Confirmed live end-to-end against **real hardware** (not just sim): real
camera video, real on-sensor AI detection, and real MAVLink telemetry from
a Cube Orange, all at once. Every mode (Tracking, Follow incl. live
separation override, Approach-Test, abort) has been confirmed live against
the sim stack; hardware-mode testing has so far focused on camera+video+
MAVLink together rather than every mode specifically.

**Confirmed live** (superseding the "not yet build-verified" note this
paragraph originally had): showing every live detection as a tappable box
(`DetectionsOverlay.kt`) and tap-to-select (`TargetSelectionOverlay.kt`'s
`onTapSelect`) - this is exactly what a real field debugging session
proved end-to-end (see `docs/hardware-wiring.md`'s AI-detection saga):
real detection boxes rendering live on a physical phone from the actual
running hardware companion. The follow-altitude slider alongside the
separation one (`ModeControls.kt`) is still only build-verified, not yet
exercised live. See `docs/protocol.md` for the `detections_update`
message and `target_select`'s `point: true` payload shape.

Arm/disarm (with a confirmation dialog before arming) and an FC flight-mode
dropdown, in `FlightControlDock.kt` - wired through
`GroundStationClient.sendArmCommand`/`sendSetFlightMode` and
`MainViewModel.setArmed`/`setFlightMode`. (The video-record toggle
originally lived here too but has since moved to `RecordButton.kt` on the
Fly tab - see below.) A ground-control-style dark theme
(`ui/theme/Theme.kt`, `DroneColors`) is applied across the app - card-based
panels, a status-color palette (green/amber/red), and
`material-icons-extended` for icon buttons.

**Build-verified** (real `gradle assembleDebug` + installed and launched on
a physical device, no crash on launch): the full DJI-Fly-style restructure
into four tabs (`GroundStationScreen.kt` now hosts a bottom `NavigationBar`
on phones or a side `NavigationRail` on tablets/wide screens, switching
between `ui/tabs/FlyTab.kt`, `ControlTab.kt`, `AiModesTab.kt`,
`SettingsTab.kt`) - the video/selection view, direct FC control, AI
guidance modes, and connection settings each get their own screen instead
of one crowded layout. The emergency abort button is rendered outside all
tab content so it stays reachable no matter which tab is open. Also
build-verified: an **Orbit** guidance mode (the DJI "circle"/
point-of-interest shot) - `DroneMode.ORBITING` sends `orbit_radius_m`/
`orbit_altitude_m` on `mode_command` (`companion/guidance/orbit.py` on the
Pi side), `TrackingOverlay.kt` draws a rotating dashed circle around the
target while orbiting, and `TargetActionSheet.kt` pops up right after a
tap/drag target selection (DJI's focus-track flow) offering
Track/Follow/Orbit/Cancel. **Not yet functionally verified** - launch was
confirmed crash-free, but no live session against a running companion (sim
or hardware) has exercised the new tabs/modes end-to-end yet.

**Build-verified**: `GuidanceWarningBanner.kt` surfaces the Safety
Supervisor's `guidance_reason` (previously parsed into
`TrackingState.guidanceReason` but never actually displayed anywhere) as a
visible on-screen warning in the Fly tab whenever guidance is blocked -
including the obstacle-proximity trip (`companion/safety/
proximity_guard.py`: any detection, not just the tracked target, closer
than `min_obstacle_distance_m` forces the Safety Supervisor to SAFE).
Installed and launched successfully on the same physical device as before.

**Build-verified**: `TelemetryPanel.kt` now shows a live geofence status
line (`Geofence: OK` / `GEOFENCE BREACHED`) sourced from the Pi's real
`fence_enabled`/`fence_breached` telemetry fields (see `docs/protocol.md`
and `companion/mavlink/bridge.py`'s `SYS_STATUS` parsing) - only shown once
a fence is actually armed on the FC, so an operator with no fence
configured doesn't get a permanent "fence: off" line. Previously the
operator had no live visibility into geofence status at all; the only
signal was an Approach-Test abort's `guidance_reason` after the fact. Real
`gradle assembleDebug`/`assembleDebugAndroidTest` succeeded; not yet
installed on a physical device this round.

**Build-verified but not installed on a device this round** (the test
device was disconnected when this landed - `gradle assembleDebug` still
succeeded cleanly): two new **Dronie**/**Parabola** smart-shot modes
(`DroneMode.DRONIE`/`.PARABOLA` in `ModeControls.kt`, sending `mode: "dronie"`/
`"parabola"` like any other mode) - one-shot cinematic camera moves (DJI
"QuickShot" equivalent) implemented by `companion/guidance/smart_shot.py`
on the Pi side. Each shot runs for a fixed duration, keeps the camera
locked on the target via the same yaw PID Follow/Orbit use, then stops
itself - **fixed**: `companion/main.py` now resets `requested_mode` to
`IDLE` the moment a shot finishes (previously it stayed `SMART_SHOT`
forever, sending no commands but never saying so), and
`MainViewModel.kt` parses the new `supervisor_state` field on
`tracking_update` and reverts its own mode selector back to Normal RC when
it sees that happen - build-verified. Deliberately *not* done for
Follow/Orbit/Approach-Test: those can drop to `SAFE` transiently (e.g. a
brief target loss) while still meaning to resume, so auto-reverting their
selector would be misleading, and Approach-Test's boundary stop is
intentionally left "stuck" until the operator decides what's next (see
`docs/safety-case.md`).

**Real-device feedback fixes** (reported live from an actual install on a
remote-controller-mounted display, not just this dev machine's build
checks): some buttons were getting clipped/hidden on that device's
screen. Root-caused to fixed-width side-by-side layouts that squeeze
(rather than wrap or scroll) when the available width is narrower than
assumed - not a single bug but a pattern, so it's fixed everywhere it
appeared:
- `FlightControlDock.kt` restructured from a 3-wide Row (arm/disarm + FC
  mode dropdown + record button) into a full-width vertical stack of just
  arm/disarm and the FC mode dropdown - stacking removes the failure mode
  entirely regardless of screen width, and reads cleaner besides.
- `SettingsTab.kt`'s Connect/Disconnect buttons now use `Modifier.weight(1f)`
  each instead of wrapping their own content width, so they always share
  the available row width instead of one potentially overflowing.
- `TargetActionSheet.kt`'s Track/Follow/Orbit chip row now scrolls
  horizontally instead of clipping if it doesn't fit.
- **Video recording moved out of the Control tab entirely** and onto the
  Fly tab as a new dedicated `RecordButton.kt` (bottom-left of the video
  view, mirroring the abort button's position on the opposite corner) -
  per feedback that the record control should live on the main screen next
  to the camera view, not in a separate settings-style tab. Also settings
  (Pi host/port) now persist to `SharedPreferences` across app relaunches
  instead of resetting to the hardcoded defaults every time.
- **Video recording itself found and fixed a real backend bug** while
  investigating the "not working" report: `cv2.VideoWriter` never raises on
  failure to open a codec - it just returns a writer whose `isOpened()` is
  `False`, so a naive implementation reports "recording" successfully
  while silently writing nothing. `companion/comms/video_recorder.py` now
  checks `isOpened()` and falls back through `mp4v` → `XVID` → `MJPG`
  before giving up, and `main.py` only reports `recording: true` to the
  app if a codec actually opened.

**More real-device feedback, second round**: the Fly tab's record button
always showed `0:00` with no way to tell if it was actually recording -
root cause was `companion/main.py` only ever sending one `recording_state`
message, at the instant recording started, so the Android timer never
updated again even though the Pi kept recording. Fixed on the Pi side
(`process_frame` now resends it every frame while recording is active);
no Android change was needed since `MainViewModel` already overwrites its
`RecordingState` on every message, it just wasn't receiving more than one.

**New: local recording on the phone itself**, per an explicit request that
video should also save on the device, not only on the Pi -
`video/LocalVideoRecorder.kt` is a second `VideoSink` added to the same
remote video track the `SurfaceViewRenderer` already displays, encoding
with `MediaCodec` (H.264) + `MediaMuxer` (MP4) - not the WebRTC library's
own `VideoFileRenderer`, which writes raw uncompressed YUV4MPEG2 frames
(~1 GB/minute at 720p, and not a format any phone gallery/player can open
directly). All encode work runs on its own `HandlerThread`, never on the
thread WebRTC delivers frames from, so a slow encode step can't add
latency to the live view. `MainViewModel.toggleRecording()` now drives
both recordings from the same Record button (by explicit choice: both at
once, not either/or) - they're independent, so a failure on one side
doesn't affect the other.

**Fixed a real field-reported bug: "video is not saving in mobile device"**
- it actually was saving, just somewhere nobody would ever find it. Files
used to land in this app's own external files dir
(`getExternalFilesDir(DIRECTORY_MOVIES)`) - valid MP4s, but *app-private*
external storage, which no Gallery/Photos app or file manager scans. An
earlier note in this file said local recording was "confirmed live,
produces an actually-playable file on a real device" - that was true only
in the narrow sense of pulling the file via `adb`/a file manager set to
show app-private folders, which is exactly why this then read as "not
saving" from a normal operator's perspective. Fixed via a new
`LocalRecordingOutput` sealed type: on API 29+ (this app's real-world
minimum in practice), `MainViewModel.buildLocalRecordingOutput()` inserts
into `MediaStore.Video.Media` with `RELATIVE_PATH = Movies/AI Vision Drone`
and `IS_PENDING = 1`, and `LocalVideoRecorder` writes straight to the
resulting `Uri`'s file descriptor (`MediaMuxer`'s `FileDescriptor`
constructor, not a path) - no storage permission needed, since creating a
new file this app owns is exactly what scoped storage exists to allow
without one. `IS_PENDING` is cleared back to 0 only once recording
actually finishes, so nothing sees a half-written file mid-recording. The
recording now shows up directly in Gallery/Photos and any file manager
under Movies. The old app-private path (`LocalRecordingOutput.LegacyFile`)
is kept only as the API 26-28 fallback, since MediaStore's
`RELATIVE_PATH`/`IS_PENDING` columns don't exist before API 29.
**Correction**: this was originally marked "build-verified" without an
actual gradle run having happened - no gradle binary was reachable in that
session, so that claim was written prematurely. A real
`./gradlew assembleDebug` (the local gradle 8.11.1 distribution cache, no
internet needed) has since confirmed this code compiles cleanly and
produces a real `app-debug.apk`. **Still not confirmed on a real device**
- unlike this project's UI-only changes, a subtle bug here (a stride
miscalculation, a per-device encoder quirk, a MediaStore insert failing
silently) could produce a corrupt or unplayable file rather than something
visibly wrong on screen, so the next real recording on a physical device
is the actual test - report back whether it now actually appears in the
phone's Gallery/Photos app, not just whether a file can be found by
digging for it.

**Fixed a real field-reported bug: "sometimes the app shows connected but
the camera is a black screen; restarting the app fixes it."** Root cause:
`MainViewModel.connect()` only ever built `WebRtcClient` and negotiated
video once, guarded by `if (webRtcClient == null)` - the WS control
channel and WebRTC video are deliberately separate transports (M5/M6) so
a video hiccup never blocks an abort command, but that separation meant a
WS reconnect (the Pi service restarting, a brief WiFi drop) never told
WebRTC anything had happened. The control link would reconnect fine, but
the *old* `RTCPeerConnection` from before the drop just sat there, dead,
forever - nothing ever closed it or sent a fresh offer, so no new video
track or frames could arrive. Restarting the app was the only thing that
worked because it threw away the ViewModel (and the stale connection with
it) and built everything from scratch. **Fixed**: video is now
(re)established from a single place, `reestablishVideo()`, triggered by
every `LinkState.CONNECTED` transition - including the very first one, so
`connect()` no longer special-cases "first time" vs "reconnect" at all.
`AiortcVideoPipeline.handle_offer()` on the Pi side already creates a
brand new `RTCPeerConnection` per offer it receives, so nothing needed to
change there. Confirmed via a real `gradle assembleDebug` (compiles
cleanly, produces `app-debug.apk`); **not yet confirmed on a real
device** - the actual test is killing/restarting the Pi's
`ai-vision-drone` service while the phone stays on the same WiFi, and
confirming video reappears within a few seconds without touching the app.

**Fixed a real field-reported smoothness bug ("make the app smooth"):
`GroundStationScreen` used to `collectAsState()` every single piece of
live state itself** - `telemetry`, `health`, `tracking`, `detections`,
`recording`, `remoteVideoTrack`, plus the AI-mode slider values - before
threading them all down to whichever tab needed them as parameters.
Several of those (`telemetry`, `health`, `tracking`, `detections`) update
on essentially every processed frame on the Pi, up to the camera's target
FPS. Since Compose recomposition scope is the composable that actually
*reads* the changed state, that meant the read happening in
`GroundStationScreen`'s own body made *the entire screen* - navigation
bar, abort button, tab switcher, all of it - recompose 20-30 times a
second, regardless of which tab was even open or whether it needed that
specific value at all. **Fixed** by having each tab (`FlyTab`, `ControlTab`,
`AiModesTab`, `StatusTab`, `SettingsTab`) collect exactly the state flows
it actually uses directly from `MainViewModel`, instead of receiving them
as parameters from a shared parent. `GroundStationScreen` itself now only
collects `landConfirmationRequest` and `alertsMuted` (both genuinely used
in its own body, for the land-confirmation dialog and the alert player's
mute state) - it no longer recomposes at all in response to telemetry/
tracking/detection updates, confining that churn to just the tab that's
actually supposed to redraw that often (`FlyTab`, showing live video).
Confirmed via a real `gradle assembleDebug` after the full refactor;
**perceived smoothness on a real device still needs confirming** - this
fixes a real, identifiable architectural cause of jank, but there was no
profiler available to measure the before/after here.

**New: a detection-density heatmap overlay** (`control/DetectionHeatmap.kt`,
`control/DetectionHeatmapOverlay.kt`), from a direct field request ("can we
add a heatmap-like feature"). `DetectionHeatmap` is a plain-Kotlin 32x18
grid that `MainViewModel` updates on every `detections_update` message: a
detection's bbox center bumps up the heat of the cell it falls in, and
every cell decays by a small factor on every update (roughly a 30-second
half-life at typical detection-update rates) so the map favors recent
activity with a fading trail rather than accumulating into one
permanently-growing total that eventually saturates solid red. Rendered
as a translucent blue-to-red Canvas overlay on the live video
(`DetectionHeatmapOverlay`), toggled on/off from a new "HEATMAP" chip in
the Fly tab's top HUD (off by default, so it doesn't clutter the normal
view unasked). Purely a visualization - it never feeds back into tracking
or guidance, which still only ever reason about the current frame's real
detections. Build-verified only (real `gradle assembleDebug`), not yet
seen live on a real device.

**New: a target movement-trail overlay** (`control/TargetTrail.kt`,
`control/TargetTrailOverlay.kt`), from a direct field request ("add visual
patterns / spatial patterns feature," clarified as a target movement trail
rather than the density heatmap above). `TargetTrail` is a bounded ring
buffer (~60 points, not an ever-growing list) of the currently-tracked
target's bbox-center history, updated on every `tracking_update` message;
`TargetTrailOverlay` renders it as a fading line - oldest segment
near-transparent, newest fully opaque - so the operator can tell at a
glance whether the subject is moving steadily, pacing back and forth, or
circling, without having watched the whole session. Cleared whenever
tracking locks a different target, the target is lost, or the operator
aborts (see below) - it always reflects only the current tracking
session's path. Shown automatically whenever a target is tracked, no
separate toggle, since it's tied to the target box already on screen
rather than a general-purpose overlay that could clutter an empty view.
Build-verified only, not yet seen live on a real device.

**Fixed two more real field-reported bugs, both specifically about
Abort:**
- **"When I abort the mission, the selected target should be forgotten
  too."** The Pi side already reset the tracker and forgot its remembered
  appearance signature on abort, but a real, subtler bug lived on both
  sides: `_on_abort()` (`companion/main.py`) never cleared
  `_pending_selection`, so a `TARGET_SELECT` that arrived just before the
  abort (e.g. the operator finishing a drag-select right as they hit
  Abort) could survive it and silently re-lock a target one frame later
  (fixed - see the root README's M10 row). On the Android side,
  `MainViewModel.abort()` now also clears its own `tracking` and
  `trailSnapshot` state immediately, rather than waiting for the Pi's next
  `tracking_update` round-trip to reflect the same thing a frame or more
  later.
- **"Buzzer should stop."** Hitting Abort mid a fast-moving alert cascade
  (a real scenario: "Target lost" -> "Searching" -> "Returning home" all
  queued within a couple of seconds is often exactly *why* an operator
  reaches for the abort button) used to keep the TTS voice talking through
  its entire backlog for several more seconds after the abort itself had
  already taken effect, since `AlertSoundPlayer.play()` uses
  `TextToSpeech.QUEUE_ADD` and nothing ever told it to clear. **Fixed**:
  `AlertSoundPlayer.stopAll()` calls `TextToSpeech.stop()` (which both
  halts the current utterance and discards everything queued behind it),
  wired to a new `MainViewModel.stopAlerts` `SharedFlow<Unit>` that
  `abort()` emits into and `GroundStationScreen` collects.

**New: a per-detection announcement buzzer** ("Car detected", "Person
detected", ...) - a direct field request: "if anything detect by AI it
should buzzer like Car detected, person detected, this will only tell
when percentage of object goes around 50%." `MainViewModel.
emitDetectionAnnouncements()` checks every live detection in each
`detections_update` message against `OBJECT_DETECTION_ANNOUNCE_THRESHOLD`
(0.5, matching the request verbatim), and announces any class crossing it
- debounced per class name via a 6-second cooldown
(`OBJECT_DETECTION_ANNOUNCE_COOLDOWN_MS`) so an object sitting
continuously in frame (detections arrive up to the camera's target FPS)
doesn't re-announce every single frame. This required converting
`AlertEvent` from a plain enum to a sealed class - a fixed enum can't
express "one case per arbitrary detected class name" - with a new
`ObjectDetected(className)` case that computes its own spoken line
("${className} detected"). Every existing `AlertEvent.X` call site (the
original enum-style names, kept as nested `object`s under the sealed
class) kept compiling completely unchanged. Independent of
`tracking`/`emitTrackingAlerts` - this fires for *every* detected class in
frame, not just the one actively tracked, and respects the same
`alertsMuted` switch as every other alert.

All four of the above confirmed via a real `gradle assembleDebug`; none
yet heard or seen on a physical device this round.

**New: `GuidanceCommandPanel.kt`** - shows the active guidance controller's
computed velocity setpoint (vx/vy/vz/yaw rate) and whether it actually
reached the FC, live on the Fly tab next to `TelemetryPanel`. Previously
this only ever reached the Pi's own session log file, reviewable only
after the fact - the plan's own staged real-flight procedure explicitly
calls for a props-off bench dry-run "watching commanded velocities on a
dashboard before ever arming," and there was no such dashboard until now.
Only rendered while a guidance controller is actually producing a command
(Tracking-only/Normal RC don't show it). Build-verified only, not yet
exercised against a live guidance session on a real device.

**New: target-loss recovery UI** (`LandConfirmationDialog.kt`) - when a
Follow/Orbit target is lost and the on-Pi search
(`companion/guidance/target_recovery.py`) times out with low battery and
too far to safely RTL, the Pi asks before landing rather than deciding on
its own. The dialog shows distance-to-home, battery, and whether the AI
currently sees anything nearby (informational only - the operator makes
the actual call), rendered at the `GroundStationScreen` level (like the
abort button) so it's reachable regardless of which tab is open.
Dismissing it (e.g. the back button) counts as "don't land," never a
silent no-op. `GuidanceCommandPanel` also now shows "SEARCHING FOR
TARGET" instead of the usual vx/vy/vz readout while the search sweep is
active, so a yaw-only command doesn't look like an unexplained glitch.
Build-verified only, not yet exercised against a live recovery scenario
on a real device.

**Fixed a real bug found from a UI review**: the Fly tab's HUD "SAT"
readout was hardcoded to a fake `"12"` - nothing had ever wired up a real
value. `companion/mavlink/bridge.py` now parses a real `GPS_RAW_INT`
message (`satellites_visible`, correctly treating the standard `255`
sentinel as "unknown," not zero) and sends it in the `telemetry` message;
the HUD now shows the real count or `"--"`. While fixing this, also
upgraded the "GPS: FIX"/"NO FIX" indicator to use the same message's real
`fix_type` (3+ = a genuine 3D fix, per `MAV_GPS_FIX_TYPE`) instead of
inferring fix status from `lat` being non-null - a materially less
precise proxy, since a stale/degraded fix can still report a non-null
last-known position. Verified via a real MAVLink loopback test against
the mock FC (`test_bridge_reflects_real_gps_satellite_count_and_fix_type`);
not yet confirmed against a real FC's actual `GPS_RAW_INT` output.

**Fixed a second real bug found in a deep code-review audit** right next
to the one above: the HUD's "BAT" tile used two different fallbacks for
the same null field - `"0%"` for the displayed text but `100` for the
color check. Before telemetry arrives (or right after a reconnect), this
rendered a self-contradictory "0% BAT" in Safe/green - misleadingly
reassuring at exactly the moment the reading is least trustworthy. Now
uses one consistent fallback (`"--"`, neutral color), matching how
SAT/ALT/SPD already handle missing data elsewhere on the same HUD.

**New: a fifth tab, `ui/tabs/StatusTab.kt`** - a full QGroundControl-style
MAVLink telemetry dashboard (Vehicle/Position/GPS/Attitude/Navigation/
Battery/RC Input/Health cards), plus a live "home radar" compass widget
(cyan needle = the aircraft's own heading from a real `VFR_HUD` message,
red needle = the real computed bearing toward home). Every field is real,
newly-wired MAVLink data, not a placeholder - `companion/mavlink/bridge.py`
gained parsing for `ATTITUDE` (roll/pitch/yaw), `VFR_HUD` (heading/airspeed/
climb/throttle), `RC_CHANNELS.rssi`, `GPS_RAW_INT.eph`/`epv` (HDOP/VDOP), and
`BATTERY_STATUS.current_battery`; `companion/guidance/geo.py` gained a
`bearing_deg()` alongside the existing `haversine_distance_m()` so
`distance_to_home_m`/`home_bearing_deg` are computed once and shared between
the Status tab and the target-recovery RTL-vs-land estimate. Mission/ADS-B
cards from a typical QGC layout are deliberately left out - this app has
neither feature, and showing a permanently-empty card for something that
doesn't exist isn't "status," it's clutter. Verified with a new real
MAVLink loopback test against the mock FC
(`test_bridge_reflects_real_attitude_navigation_and_rc_link_fields`) and a
clean `gradle assembleDebug`; not yet confirmed against a real FC's actual
output for these new message types.

**New: buzzer + voice alerts** (`audio/AlertEvent.kt`,
`audio/AlertSoundPlayer.kt`) - a short tone (`ToneGenerator`) immediately
followed by a spoken line (`TextToSpeech`, e.g. "Target locked", "Target
lost", "Following target", "Returning home") on real tracking/guidance
state transitions, so an operator whose eyes are on the aircraft still
knows what it just did. Strictly edge-triggered in `MainViewModel` (fires
once per real transition - target acquired/lost, Follow/Orbit/Search
engaged, a forced safety stop, an autonomous RTL inferred from a real
`fc_mode` change, a geofence breach, a land-confirmation prompt - never
once per telemetry frame, since most of these fields are otherwise re-sent
unchanged on every tick). A mute switch lives on the new Status tab.
Build-verified; not yet heard on a physical device this round.

**New: a live speed slider for Follow/Orbit** (`ModeControls.kt`) - the
same live-update pattern as the existing separation/altitude/radius
sliders, sending `follow_max_speed_mps`/`orbit_max_speed_mps` on
`mode_command`. On the Pi side, `FollowController.set_max_speed()`/
`OrbitController.set_max_speed()` (`companion/guidance/follow.py`,
`companion/guidance/orbit.py`) clamp the request to
`[min_speed_mps, the configured max_speed_mps ceiling]` from
`follow_limits.yaml`/`orbit_limits.yaml` - the slider can only ever make
the drone *slower* than its safety-vetted config ceiling, never faster
than it from a phone mid-flight (raising the actual ceiling requires
editing config and is deliberately not an in-flight control). **Fixed a
real bug before it shipped**: each guidance PID's own `out_limit` is baked
in at construction from the initial `max_speed_mps` - naively mutating the
limits dict alone (like the separation/altitude live-updates do) would
have left every PID's internal clamp stuck at the old value, so raising
the slider would have silently done nothing while lowering it would have
"worked" only because the separate outer clamp happened to be more
restrictive. `set_max_speed()` updates each PID's `out_limit` directly,
caught by a new test that drives the PID hard enough to saturate on its
own, not just the outer clamp. Build-verified.

**Fixed a real field-reported bug: "I can't disarm from the app."** The
DISARM button showed correctly and sent the command, but the drone stayed
armed - root cause is on the flight-controller side, not this app:
ArduCopter refuses a normal (unforced) `MAV_CMD_COMPONENT_ARM_DISARM` if
its own land-detector believes the aircraft is flying, a real documented
behavior (confirmed against pymavlink's own bundled command definitions,
not guessed) that a bench test with props spinning can trip as a false
positive - and `MavlinkBridge` never listened for `COMMAND_ACK`, so the
rejection was invisible on both ends. Fixed with a `force` flag through to
`MAV_CMD_COMPONENT_ARM_DISARM`'s own documented param2=21196 override,
surfaced as a separate, deliberately less-prominent **"Force disarm"**
text button in `FlightControlDock.kt` (only shown while armed, own
stronger confirmation dialog warning it overrides the FC's in-flight
protection) - kept apart from the main DISARM button so it's never reached
for by accident, and never wired to arming at all, so a stray `force` can't
bypass a pre-arm check. Build-verified.

**Fixed a real field-reported bug: light theme rendered dark-styled cards
on a light page.** An earlier pass added a real `DroneGroundStationTheme`
with proper `darkColorScheme`/`lightColorScheme` instances and wired a
working dark/light toggle (`MainViewModel.isDarkMode` → `SettingsTab.kt`),
but left `DroneColors` - the object every screen actually uses for its own
colors (`DroneColors.Surface`, `.TextPrimary`, etc., not
`MaterialTheme.colorScheme` directly) - hardcoded to permanently-dark
values, per its own comment: "Explicit dark theme default colors to
prevent non-composable invocation errors." That workaround is why light
mode looked broken: the Scaffold background correctly turned light
(it reads `MaterialTheme.colorScheme.background`), but every `Card`/
button/text across all ~20 files using `DroneColors` stayed dark, since
that object never changed. Root cause of the original compile error:
several `DroneColors`-reading helpers (e.g. `StatusTab.kt`'s
`batteryColor()`/`gpsFixColor()`) are plain (non-`@Composable`) functions,
which can't call a `@Composable get()` property - simply making
`DroneColors`'s properties composable would have broken those call sites
again. Fixed properly instead: `DroneColors`'s properties are now plain
(non-composable) getters backed by a `mutableStateOf` palette that
`DroneGroundStationTheme` swaps on theme change - Compose's snapshot
system still tracks and recomposes on reads of a `State.value` regardless
of whether the *reading* function is itself `@Composable`, so every
existing `DroneColors.X` call site keeps compiling completely unchanged
while now actually responding to the theme. Also designed a real light
palette rather than inverting the dark one's hues: the dark theme's brand
yellow accent (`#FFCC00`) has poor contrast on a white/light-gray surface,
so light mode uses a darkened amber (`#9C6B00`) for Accent/Warning
instead. Build-verified (`assembleDebug` + `assembleDebugAndroidTest`);
not yet confirmed against a physical device in both themes this round.

## Layout

```
app/src/main/java/com/aivisiondrone/groundstation/
  comms/        Protocol.kt (wire schema, mirrors companion/comms/protocol.py),
                GroundStationClient.kt (OkHttp WebSocket client), JsonExt.kt
  video/        WebRtcClient.kt (receive-only WebRTC peer connection),
                LocalVideoRecorder.kt (MediaCodec/MediaMuxer VideoSink -
                saves the video locally on this device)
  control/      TargetSelectionOverlay.kt (tap-to-select + drag-to-select),
                DetectionsOverlay.kt (all live detections, labeled),
                DetectionHeatmap.kt / DetectionHeatmapOverlay.kt (opt-in
                detection-density heatmap over the live video),
                TargetTrail.kt / TargetTrailOverlay.kt (fading movement
                trail for the currently-tracked target),
                TrackingOverlay.kt (tracked box + rotating orbit ring),
                TargetActionSheet.kt (Track/Follow/Orbit/Cancel quick menu),
                GuidanceWarningBanner.kt (shows why guidance stopped, e.g.
                obstacle too close, RC override, target lost),
                GuidanceCommandPanel.kt (live commanded vx/vy/vz/yaw_rate
                and whether it actually reached the FC - the bench-test
                "dashboard" the plan's staged real-flight procedure calls
                for, previously only in the Pi's session log),
                LandConfirmationDialog.kt (target-loss recovery's
                operator-approval gate before an autonomous landing),
                ModeControls.kt (mode buttons, incl. Dronie/Parabola smart
                shots, + follow/orbit sliders),
                FlightControlDock.kt (arm/disarm, FC mode dropdown - a
                full-width vertical stack, not a Row, for narrow-screen
                safety), RecordButton.kt (local video record toggle),
                AbortButton.kt
  telemetry/    TelemetryModels.kt, TelemetryPanel.kt, HealthPanel.kt
  audio/        AlertEvent.kt (edge-triggered tracking/guidance state-change
                events), AlertSoundPlayer.kt (ToneGenerator beep +
                TextToSpeech voice line per event, STREAM_MUSIC)
  ui/           GroundStationScreen.kt (Scaffold + bottom nav/side rail
                host), AppTab.kt, LinkStatusChip.kt,
                theme/Theme.kt (dark ground-control color scheme)
  ui/tabs/      FlyTab.kt (video + overlays + quick action sheet + the
                main-screen RecordButton), ControlTab.kt (FlightControlDock,
                full screen), AiModesTab.kt (ModeControls + live detections
                list), StatusTab.kt (full MAVLink telemetry dashboard + the
                live home-radar compass widget + alerts mute switch),
                SettingsTab.kt (Pi host/port connection, persisted
                to SharedPreferences)
  MainActivity.kt, MainViewModel.kt (MVVM glue, incl. alert-event
  edge-detection off telemetry/tracking_update transitions)

app/src/androidTest/java/com/aivisiondrone/groundstation/
  GroundStationScreenTest.kt (instrumented Compose UI tests - abort
  reachability across every tab, mode controls in the AI Modes tab,
  flight control dock in the Control tab, drag-gesture smoke test)
```

## Known gaps

- ~~Follow-mode separation slider is UI-local only~~ - fixed: `setMode`/
  `setFollowSeparation` now send `follow_separation_m` on `mode_command`,
  and the Pi applies it live to the running `FollowController` (see
  `docs/protocol.md`). Not yet tried against a live Follow session on
  a real phone.
- ~~No reconnect/retry logic on WebSocket drop~~ - fixed: `GroundStationClient`
  tracks `shouldAutoReconnect` (true after `connect()`, false after an
  explicit `disconnect()`), and `MainViewModel` retries every 3s while a
  drop is unexpected. Not yet tried against a real dropped link (e.g.
  walking out of WiFi range).
- ~~No instrumented (Espresso) tests yet~~ - added
  `app/src/androidTest/.../GroundStationScreenTest.kt`: abort-button
  reachability (on launch and after a mode switch), mode controls visible,
  and a drag-gesture smoke test. **Not yet run** - this dev environment has
  no emulator/device to run instrumented tests on; run via Android
  Studio's test runner or `./gradlew connectedAndroidTest` on a connected
  device.
- ~~Pi host/port reset to hardcoded defaults every relaunch~~ - fixed:
  `SettingsTab.kt` now persists both to `SharedPreferences`, saved when
  Connect is tapped.
- ~~Mode selector doesn't auto-revert to Normal RC when a Dronie/Parabola
  smart shot finishes~~ - fixed on both ends: `companion/main.py` resets
  `requested_mode` to `IDLE` when the shot finishes, and `MainViewModel`
  now parses `supervisor_state` and mirrors that. Approach-Test's
  `STOPPED_AT_BOUNDARY`/`ABORTED` deliberately still don't auto-revert -
  see `docs/safety-case.md` for why that's intentional, not the same gap.
