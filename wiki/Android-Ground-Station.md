# Android Ground Station

A native Kotlin / Jetpack Compose single-activity app (`android/`). It connects to the Pi over a WebSocket for control and telemetry, and a separate WebRTC peer connection for video, so a video hiccup never blocks STOP.

- minSdk 26, targetSdk 34, compileSdk 35.
- Package `com.aivisiondrone.groundstation`.
- Connection: the Pi's IP and port `8765`, entered in **Settings** and remembered between launches.

## Tabs

| Tab | What is on it |
|---|---|
| **Fly** | Live video with detection boxes, the tracked target box and its movement trail, orbit ring, tap/drag target selection, the Track / Follow / Orbit / Arm & Follow quick sheet, guidance banner, record button, HUD chips (Teach, Heatmap, Perimeter), link status |
| **Control** | Arm / Disarm (with confirmation), separate **Force disarm** control (stronger confirmation), flight-mode dropdown |
| **AI Modes** | Mode buttons (Normal RC, Track, Follow, Orbit, Approach), Follow separation / altitude / speed sliders, Orbit radius / altitude / speed, Grid Search card, list of live detections with Select |
| **Status** | Full telemetry dashboard (vehicle, position, GPS, attitude, navigation, battery, RC input, health), home-radar compass, offline flight map, alerts mute switch |
| **Settings** | Pi host and port, Connect; dark / light theme |

The **STOP / ABORT** button is reachable on every tab.

## Picking and following a target

1. On the Fly tab, **tap** a detection box, or **drag** a box around the target. The Pi matches your selection to the nearest real detection.
2. The quick sheet opens: **Track** (watch only), **Follow**, **Orbit**, or **Arm & Follow** (shown only while disarmed).
3. Choosing a guidance mode makes the Pi request `GUIDED` automatically (never while the pilot is moving the sticks). Guidance runs only once the FC is actually in `GUIDED`.
4. Adjust separation, altitude or speed on the AI Modes tab; the Pi clamps every value to the configured limits.

**Arm & Follow** arms (after the usual "motors will become live" confirmation), sends `auto_takeoff`, climbs to 10 m, and only then starts following. See [Guidance Modes](Guidance-Modes#arm--follow-auto-takeoff).

## What the app tells you

### Guidance banner

- **Blocked** (red): the Safety Supervisor refused guidance, with the reason - FC not in GUIDED, RC override, link lost, target lost, obstacle too close, geofence breached, battery critical, or a stale subsystem. A **Resume** button appears after an RC override.
- **Holding** (amber): guidance is allowed but deliberately holding still - climbing after takeoff, target unseen for 0.3 s or more, identity in doubt, degraded GPS (Grid Search), or a refused takeoff (bad GPS or low battery).

### Guidance command panel

Shows the live commanded vx / vy / vz / yaw rate and whether it actually reached the FC (`GUIDANCE SENT` / `BLOCKED`). This is the dashboard for the props-off bench tests.

### Voice and tone alerts

Each fires once per real transition, never per frame:

| Alert (spoken) | When |
|---|---|
| Target locked / Target lost | Tracking state changes |
| Following target / Orbit engaged / Grid search engaged | Guidance actually starts (Follow waits for `guidance_sent`, so it is not announced during the takeoff climb) |
| Searching for target / Target not found. Returning home | Target-loss recovery |
| Landing confirmation needed | Recovery wants to land in place - a dialog asks you |
| Guidance stopped. Pilot in control | Guidance interrupted by RC override |
| Geofence breached | FC reports a fence breach |
| Perimeter breach detected / Perimeter clear | A detection enters / leaves your drawn zone |
| Can't start. No target locked / Can't start. Flight controller not in Guided mode / Guidance rejected | A mode was refused |
| Arm rejected / Disarm rejected by flight controller | The FC refused (e.g. pre-arm checks) |
| Flight controller did not change mode | A mode request was never confirmed after 3 tries |
| Climbing to follow altitude / Target not visible. Holding position / Not sure this is your target. Holding position | A hold started |

STOP clears the alert queue immediately.

## Other features

| Feature | Notes |
|---|---|
| **Recording** | The record button starts the Pi's own recording (kept even if Wi-Fi degrades) **and** a phone-side copy saved to `Movies/AI Vision Drone` in the Gallery. The timer counts up live. |
| **Teach mode** | The TEACH NEW OBJECT chip → drag a box → name it and optionally give its real size. See [Teach Mode](Teach-Mode). |
| **Detection heatmap** | HEATMAP chip: a 32x18 grid of where detections occur, decaying over ~30 s. Off by default. |
| **Target trail** | A fading line of the tracked target's recent path (~60 points). |
| **Perimeter alert** | PERIMETER chip: drag a zone on the video; an alert fires when any detection enters it. Runs independently of guidance. |
| **Offline flight map** | Status tab: home, aircraft position and heading, flight path, planned Grid Search route. Vector-drawn, no map tiles, no internet. |
| **Grid Search card** | Width and height sliders, Start / Stop, live "leg X of Y". Start is disabled without a GPS fix. |
| **Land confirmation dialog** | Target-loss recovery never lands without your explicit approval. |

## Link behaviour

- The app sends a `ping` every 500 ms. The Pi treats 3 s of silence as a lost link and stops guidance; 15 s while the Pi holds the aircraft in GUIDED triggers one RTL request.
- On an unexpected drop the app retries every 3 s. Each reconnect renegotiates the video.
- The link chip shows CONNECTED / CONNECTING / DISCONNECTED.
- If the phone falls about a second behind on updates (weak Wi-Fi), the Pi closes it with code 1013 and it reconnects fresh. The app currently only notices this when its socket fails, which can take up to ~10 s; handling `onClosing` in `GroundStationClient` would make it immediate.

## Building

**Android Studio:** open `android/`, sync, Run.

**Command line** (JDK 17+ and an Android SDK; `android/local.properties` points at the SDK):

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.aivisiondrone.groundstation/.MainActivity
```

Instrumented UI tests (STOP reachable on every tab, mode controls, drag gesture): `./gradlew connectedAndroidTest` on a device. They have not been run yet.

## Code layout

```
comms/      Protocol.kt (wire schema), GroundStationClient.kt (OkHttp WebSocket + 500 ms ping), JsonExt.kt
video/      WebRtcClient.kt (receive-only), LocalVideoRecorder.kt (MediaCodec/MediaMuxer to MediaStore)
control/    selection, detection, trail, heatmap, perimeter, map, grid search, banners, dock, mode buttons, STOP
telemetry/  TelemetryModels.kt, TelemetryPanel.kt, HealthPanel.kt
audio/      AlertEvent.kt, AlertSoundPlayer.kt (tone + text-to-speech)
ui/         GroundStationScreen.kt, AppTab.kt, LinkStatusChip.kt, theme/, tabs/
MainViewModel.kt  state, message handling, alert edge-detection
```

Each tab collects only the state it needs, so a telemetry update does not recompose the whole screen. Message and alert collectors are wrapped so one malformed message cannot silently stop all updates.

## Status

Confirmed on a real phone against the real Pi: connect, video, tap/drag selection, tracking overlay, arm/disarm, mode dropdown, guidance buttons, obstacle banner, record timer, phone-side recording. Built but not yet seen on a device: heatmap, perimeter alert, flight map, Grid Search UI, alert audio, hold banners.
