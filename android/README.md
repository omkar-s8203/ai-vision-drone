# Android Ground Station

Native Kotlin, Jetpack Compose, single-activity app (docs plan M6). Talks to
the Pi's `companion/comms` layer: a WebSocket control/telemetry channel and
a separate WebRTC video channel, per `docs/protocol.md`.

## Status

**Builds, runs, and works end-to-end** - confirmed live on a real device
against the Pi's sim companion stack over real WiFi: connects, streams
synthetic video, drag-to-select correctly initializes tracking on the
target, and the tracking overlay updates live. This project's dev
environment has no Android SDK, so every fix below came from you pasting
back a real build/runtime error - that's the expected way this gets
verified from here on out.

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

Confirmed live end-to-end against **real hardware** (not just sim): real
camera video, real on-sensor AI detection, and real MAVLink telemetry from
a Cube Orange, all at once. Every mode (Tracking, Follow incl. live
separation override, Approach-Test, abort) has been confirmed live against
the sim stack; hardware-mode testing has so far focused on camera+video+
MAVLink together rather than every mode specifically.

**New, not yet build-verified**: showing every live detection as a tappable
box (`DetectionsOverlay.kt`), tap-to-select (`TargetSelectionOverlay.kt`'s
`onTapSelect`), and a follow-altitude slider alongside the separation one
(`ModeControls.kt`) - see `docs/protocol.md` for the `detections_update`
message and `target_select`'s new `point: true` payload shape. These
compile-clean by inspection but haven't been through a real Android Studio
build yet - expect the usual round of paste-back-the-error fixes.

Arm/disarm (with a confirmation dialog before arming), an FC flight-mode
dropdown, and a video-record toggle with a live duration readout, all in
`FlightControlDock.kt` - wired through
`GroundStationClient.sendArmCommand`/`sendSetFlightMode`/`sendRecordCommand`
and `MainViewModel.setArmed`/`setFlightMode`/`toggleRecording`. A
ground-control-style dark theme (`ui/theme/Theme.kt`, `DroneColors`) is
applied across the app - card-based panels, a status-color palette
(green/amber/red), and `material-icons-extended` for icon buttons.

**Newest, not yet build-verified**: full DJI-Fly-style restructure into four
tabs (`GroundStationScreen.kt` now hosts a bottom `NavigationBar` on phones
or a side `NavigationRail` on tablets/wide screens, switching between
`ui/tabs/FlyTab.kt`, `ControlTab.kt`, `AiModesTab.kt`, `SettingsTab.kt`) -
the video/selection view, direct FC control, AI guidance modes, and
connection settings each get their own screen instead of one crowded
layout. The emergency abort button is rendered outside all tab content so
it stays reachable no matter which tab is open. Also new: an **Orbit**
guidance mode (the DJI "circle"/point-of-interest shot) - `DroneMode.ORBITING`
sends `orbit_radius_m`/`orbit_altitude_m` on `mode_command`
(`companion/guidance/orbit.py` on the Pi side), `TrackingOverlay.kt` draws a
rotating dashed circle around the target while orbiting, and a new
`TargetActionSheet.kt` pops up right after a tap/drag target selection
(DJI's focus-track flow) offering Track/Follow/Orbit/Cancel instead of
requiring a trip to a separate mode screen. None of this has been through a
real Android Studio build yet - the four-tab restructure in particular
touches almost every screen, so expect a real round of build errors.

## Layout

```
app/src/main/java/com/aivisiondrone/groundstation/
  comms/        Protocol.kt (wire schema, mirrors companion/comms/protocol.py),
                GroundStationClient.kt (OkHttp WebSocket client), JsonExt.kt
  video/        WebRtcClient.kt (receive-only WebRTC peer connection)
  control/      TargetSelectionOverlay.kt (tap-to-select + drag-to-select),
                DetectionsOverlay.kt (all live detections, labeled),
                TrackingOverlay.kt (tracked box + rotating orbit ring),
                TargetActionSheet.kt (Track/Follow/Orbit/Cancel quick menu),
                ModeControls.kt (mode buttons + follow/orbit sliders),
                FlightControlDock.kt (arm/disarm, FC mode dropdown, record
                toggle), AbortButton.kt
  telemetry/    TelemetryModels.kt, TelemetryPanel.kt, HealthPanel.kt
  ui/           GroundStationScreen.kt (Scaffold + bottom nav/side rail
                host), AppTab.kt, LinkStatusChip.kt,
                theme/Theme.kt (dark ground-control color scheme)
  ui/tabs/      FlyTab.kt (video + overlays + quick action sheet),
                ControlTab.kt (FlightControlDock, full screen),
                AiModesTab.kt (ModeControls + live detections list),
                SettingsTab.kt (Pi host/port connection)
  MainActivity.kt, MainViewModel.kt (MVVM glue)

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
