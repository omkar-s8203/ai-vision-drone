# Android Ground Station

Native Kotlin, Jetpack Compose, single-activity app (docs plan M6). Talks to
the Pi's `companion/comms` layer: a WebSocket control/telemetry channel and
a separate WebRTC video channel, per `docs/protocol.md`.

## Status

Code-complete skeleton, **not yet build-verified** - this was written
without Android Studio/an Android SDK available in the dev environment that
produced it. Before relying on it:

1. Open `android/` in Android Studio (this generates the Gradle wrapper jar
   automatically on first sync - `gradle/wrapper/gradle-wrapper.properties`
   is already in place, pointing at Gradle 8.7).
2. Let it resolve dependencies (needs network access to Google's Maven and
   Maven Central) and fix any compile errors it surfaces - most likely
   candidates are the `org.webrtc.*` API surface in `video/WebRtcClient.kt`
   (written from the well-known WebRTC-Android sample pattern, but not
   checked against the exact `stream-webrtc-android:1.1.1` version pinned
   in `app/build.gradle.kts`) and Compose Material3 API drift.
3. Run it against the Pi's sim mode (`COMPANION_MODE=sim python -m companion.main`
   on a machine reachable from the phone) to validate the control channel
   end-to-end; video needs the Pi's `video` optional dependency group
   installed and an actual `AiortcVideoPipeline` wired into the orchestrator
   (currently optional/unwired by default - see `companion/main.py`).

## Layout

```
app/src/main/java/com/aivisiondrone/groundstation/
  comms/        Protocol.kt (wire schema, mirrors companion/comms/protocol.py),
                GroundStationClient.kt (OkHttp WebSocket client), JsonExt.kt
  video/        WebRtcClient.kt (receive-only WebRTC peer connection)
  control/      TargetSelectionOverlay.kt (drag-to-select), TrackingOverlay.kt
                (bbox/id/confidence), ModeControls.kt, AbortButton.kt
  telemetry/    TelemetryModels.kt, TelemetryPanel.kt, HealthPanel.kt
  ui/           GroundStationScreen.kt (top-level layout)
  MainActivity.kt, MainViewModel.kt (MVVM glue)
```

## Known gaps

- Follow-mode separation slider is UI-local only - live separation override
  isn't in the wire protocol yet (Pi reads it from `follow_limits.yaml` at
  startup). Adding a `mode_command` payload field for it is a small,
  contained follow-up.
- No reconnect/retry logic on WebSocket drop yet - `GroundStationClient`
  reports `DISCONNECTED` but the UI doesn't auto-retry.
- No instrumented (Espresso) tests yet, per the plan's M6 testing section.
