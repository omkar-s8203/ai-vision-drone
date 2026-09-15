# Android Ground Station

Native Kotlin, Jetpack Compose, single-activity app (docs plan M6). Talks to
the Pi's `companion/comms` layer: a WebSocket control/telemetry channel and
a separate WebRTC video channel, per `docs/protocol.md`.

## Status

**Builds and runs** - confirmed on a real device, rendering the full UI
(health/telemetry panels, mode controls, abort button, connect fields).
This project's dev environment has no Android SDK, so every fix below came
from you pasting back a real build/runtime error - that's the expected way
this gets verified from here on out.

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

Still to validate against the real Pi (not just this environment's tests):
run the app against the Pi's sim mode (`COMPANION_MODE=sim python -m companion.main`
on a machine reachable from the phone, with the Pi's `video` optional
dependency group installed - `pip install .[video]`) to confirm target
selection, mode switching, and video actually work end-to-end over WiFi.

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
