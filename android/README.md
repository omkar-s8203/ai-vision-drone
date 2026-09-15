# Android Ground Station

Native Kotlin, Jetpack Compose, single-activity app (docs plan M6). Talks to
the Pi's `companion/comms` layer: a WebSocket control/telemetry channel and
a separate WebRTC video channel, per `docs/protocol.md`.

## Status

Code-complete skeleton, currently being build-verified against a real
Android Studio/Gradle setup (this project's dev environment has no Android
SDK, so this only gets checked when you build it). Fixed so far:

- **Kotlin/Compose plugin version mismatch**: `org.jetbrains.kotlin.plugin.compose`
  only exists from Kotlin 2.0.0 onward (it replaced the old
  `composeOptions{ kotlinCompilerExtensionVersion }` approach). The root
  `build.gradle.kts` originally pinned Kotlin 1.9.24 alongside it - bumped
  both `org.jetbrains.kotlin.android` and `org.jetbrains.kotlin.plugin.compose`
  to 2.0.21.

Still to confirm on a real sync/build:
1. The `org.webrtc.*` API surface in `video/WebRtcClient.kt` (written from
   the well-known WebRTC-Android sample pattern, not checked against the
   exact `stream-webrtc-android:1.1.1` version pinned in `app/build.gradle.kts`)
   and Compose Material3 API drift.
2. Run it against the Pi's sim mode (`COMPANION_MODE=sim python -m companion.main`
   on a machine reachable from the phone) to validate the control channel
   and video end-to-end - both are wired in by default in sim mode now
   (`companion/main.py`'s `build_sim_orchestrator`), provided the Pi side has
   the `video` optional dependency group installed (`pip install .[video]`).

**If you hit another Gradle/compile error, paste it back and it'll get fixed the same way** - that's the expected, normal way this gets verified without an SDK on this end.

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
