# Tools

## `live_monitor.py` (implemented, unit-tested)

Live terminal view of everything the Pi sends to the app (telemetry, tracking/guidance state and
commanded velocities, health, detections, one-off events), one readable line each, auto-reconnecting.
**Read-only** - it never sends a message, because the Pi judges the phone's liveness from the
messages it receives and a monitor that sent anything could hide a dead phone link.

```
pip install websockets
python tools/live_monitor.py --uri ws://<pi-ip>:8765          # or ws://127.0.0.1:8765 on the Pi
python tools/live_monitor.py --uri ws://<pi-ip>:8765 --only tracking_update --rate 5
```

High-rate types are throttled (default 2 lines/s per type) but flight-mode/arm/guidance changes
and events are always shown at once. The Pi's own log lines are separate:
`ssh omkar@<pi-ip> journalctl -u ai-vision-drone -f`.

## `calibrate_camera.py` (implemented, unit-tested)

OpenCV checkerboard-based camera intrinsics calibration (M4, Distance
Estimation) - fits `fx`/`fy`/`cx`/`cy` from a set of checkerboard photos
and writes `companion/config/camera_calibration.yaml` directly, which
`companion/guidance/distance.py`'s pinhole distance estimator reads.

```
python tools/calibrate_camera.py --images "calib_photos/*.jpg" \
    --board-cols 9 --board-rows 6
```

Run `python tools/calibrate_camera.py --help` for the full option list
(board size, output path, `--dry-run` to preview without writing). See the
module's own docstring for how to capture a good set of calibration
photos on the Pi.

**Not yet run against real hardware photos** - built and tested (both real
unit tests of its file-globbing/corner-detection/validation logic, and a
manual end-to-end CLI smoke test with synthetic multi-view checkerboard
images) on this dev machine, which has no camera to capture real photos
with. `companion/config/camera_calibration.yaml` still holds the
placeholder intrinsics noted in that file until this is run for real on
the Pi against the actual AI Camera - confirmed directly on the Pi (not
assumed): the tool has never appeared in shell history there, and the
config file is still byte-for-byte the original placeholder. (An earlier
version of this note claimed the real run had happened; that was
mistaken and is corrected here once the discrepancy was actually
checked.)

## `distance_validation.py` (implemented, unit-tested)

Validates the vision-only pinhole distance estimator (`companion/guidance/
distance.py`) against docs plan M4's own measured-ground-truth acceptance
test: place a test subject at known distances (the plan's own example:
2m/5m/10m/20m) and compare the estimate against reality - **target: <15%
error within the 3-15m range**.

```
python tools/distance_validation.py --template > measurements.json
# fill in each bbox_w_px from the real detector output at that distance
python tools/distance_validation.py measurements.json
```

**Blocked on two real-world inputs, not more code**: (1) real camera
intrinsics from `calibrate_camera.py` above - not yet run, so this would
currently validate against placeholder `fx`/`fy` values, which is
meaningless; (2) a real set of measurements - the actual bounding-box
pixel width the detector reports for a test subject standing at each
known, physically-measured distance. The validation math itself
(`validate()`) is fully unit-tested against synthetic intrinsics/
measurements (`companion/tests/test_distance_validation.py`), including
the "only average points inside the plan's own 3-15m validated range"
rule and graceful handling of missing/unknown-class measurements.

## `imx500_convert.py` (implemented, unit-tested)

Wrapper around Raspberry Pi/Sony's `imx500-converter` toolchain for
deploying custom-trained models to the Raspberry Pi AI Camera (M2) - only
needed if a required object class isn't covered by the stock COCO model
this project ships with.

```
python tools/imx500_convert.py my_model.onnx --out imx500_converted/
```

Picks `imxconv-pt` for a `.onnx` model or `imxconv-tf` for a `.h5`/`.pb`/
`.keras` model or a SavedModel directory, per Raspberry Pi's own
documented framework split. Validates the tool is installed with a clear
error otherwise, and that a `.rpk` file actually came out the other end.

**The wrapper's own logic (converter selection, error handling, output
validation) is unit-tested with the real CLI mocked out**
(`companion/tests/test_imx500_convert.py`) - **the `-i`/`-o` flags
themselves are not independently verified against the real `imxconv-tf`/
`imxconv-pt` tool**, since installing `imx500-converter` needs a specific
Python 3.9-3.11 x86_64 Linux environment not available on this dev
machine. Run `imxconv-tf --help` / `imxconv-pt --help` once it's actually
installed and check `CONVERTER_ARGS` at the top of the file before
trusting this against a real model.

## `benchmark_detection.py` (implemented, unit-tested)

Measures the real detection pipeline against docs plan M2's own
acceptance criteria - not arbitrary numbers: **>= 15 FPS at 720p+, < 60ms
p95 per-frame detection latency, < 15% mean Pi 5 CPU usage from detection
alone**. Detection has been confirmed *working* on real hardware, but
never formally *measured* against these until this tool exists.

```
python tools/benchmark_detection.py --duration 30
```

Point the camera at a moving human/vehicle subject first, per the plan's
own acceptance test. Prints a PASS/FAIL report per metric. CPU measurement
needs the optional `psutil` dependency (`pip install -e .[benchmark]`) -
degrades to "unavailable" rather than failing if it isn't installed.

**Not yet run against real hardware** - the measurement logic itself is
unit-tested against a synthetic camera/detector
(`companion/tests/test_benchmark_detection.py`), but the actual FPS/
latency/CPU numbers this milestone needs can only come from running it for
real on the Pi with the real AI Camera.

**Real field issue found and fixed**: running this (or `detection_regression.py
capture`) while the `ai-vision-drone` systemd service is already running
fails with a bare `OSError: [Errno 16] Device or resource busy` from deep
inside picamera2/V4L2 - the camera can only be held open by one process at
a time, and the raw error gives no hint why. Both tools now share
`companion.vision.camera.open_real_camera_and_detector()`, which catches
this specific failure and re-raises a clear, actionable message instead:
stop the service first (`sudo systemctl stop ai-vision-drone`), run the
tool, then restart it (`sudo systemctl start ai-vision-drone`) since it
normally auto-starts on boot.

## `detection_regression.py` (implemented, unit-tested)

The practical equivalent of the plan's "recorded-video regression set" for
this specific camera's architecture: since the IMX500 runs inference
*on the sensor* at capture time, a saved video file can't be replayed
through it afterward the way you'd replay a clip through an off-sensor
model - there's no "detection" to re-run, only a raw image. So instead of
recording video and re-running detection on it later, this records a live
session's *detection results* (class/score/bbox per frame) and analyzes
that stream for frame-to-frame consistency - stable detection while a
subject is in view is exactly what a regression would break, and this
would have caught the exact class of bug this project already hit once for
real (`docs/hardware-wiring.md`'s `capture_request()` saga, where
detections silently stopped arriving).

```
python tools/detection_regression.py capture --duration 30 --out session.json
python tools/detection_regression.py analyze session.json
```

`analyze` reports two things from the same captured session file:

1. **Detection stability (M2)**: detection rate, the longest run of
   consecutive zero-detection frames (the key regression signal - a sudden
   long gap where there previously wasn't one), detection-score stability,
   and bounding-box position jitter frame-to-frame. Also doubles as real
   data for tuning `camera.score_threshold` (`hardware.yaml`) against
   actual score distributions instead of leaving it as an untuned guess.
2. **Tracking reacquisition (M3)**: replays the same captured detections
   through the real `TrackingStateMachine`/`IouKalmanTracker`
   (`replay_through_tracker()`) and reports against the plan's own M3
   acceptance metrics - **reacquisition success rate ≥ 90%, false-lost
   rate ≤ 5%**. This reuses whatever session `capture` already recorded on
   real hardware for M2 - no separate M3 capture step needed, since a
   captured session already contains exactly the per-frame
   detection-present/absent sequence tracking reacquisition depends on.

**Not yet run against real hardware** - `analyze_session()` and
`replay_through_tracker()` (the actual stability/reacquisition math) are
unit-tested against synthetic session data
(`companion/tests/test_detection_regression.py`); `capture` needs the real
Pi and camera. Once a first real session is captured, save it (e.g. as
`tools/reference_sessions/baseline.json`) and re-run `analyze` against a
fresh capture after any future change to the detection/camera/tracking
pipeline to compare against it by eye - there's no automated pass/fail
threshold for drift between two sessions yet (jitter/score distributions
will legitimately vary session to session with lighting/distance/subject),
just the tool to make that comparison possible.

## `ws_latency_benchmark.py` (implemented, unit-tested)

Measures the WS control/telemetry channel's round-trip time against docs
plan M5's own acceptance metric: **WS control round-trip < 50ms**. Adds a
real `ping`/`pong` message pair (`docs/protocol.md`) answered directly
inside `GroundStationLink._dispatch` - bypassing every app-level handler -
so this measures the transport's own latency floor, not anything
downstream of it (guidance, tracking, etc. were never on this path).

Against the real running companion service, from a laptop on the same
WiFi as the Pi (the actual M5 scenario):

```
python tools/ws_latency_benchmark.py --uri ws://<pi-ip>:8765 --count 100
```

Or a local sanity check with no Pi involved at all (spins up its own
`GroundStationLink` on localhost and measures against that):

```
python tools/ws_latency_benchmark.py --self-test
```

Prints a PASS/FAIL report (mean + p95 round-trip ms). Unit-tested against
a real local WebSocket server, not a fake transport
(`companion/tests/test_ws_latency_benchmark.py`), since the entire point
is measuring real transport latency.

**Not yet run against the real Pi over real WiFi** - `--self-test` confirms
the ping/pong plumbing itself works (loopback RTT ~0ms, as expected), but
the real M5 number can only come from running this against the Pi's actual
WS server from a phone/laptop at realistic field range.

Video glass-to-glass latency (M5's other metric, < 200ms) is not covered
by this tool - it's a separate manual test. `companion/comms/
video_pipeline.py`'s `overlay_latency_timestamp()` now supports it: set
`AI_VISION_DRONE_LATENCY_OVERLAY=1` before starting the companion service
(hardware mode only) and every video frame gets a wall-clock timestamp
burned into its corner before WebRTC encodes it. Read that timestamp off
the Android-rendered frame (e.g. pause a screen recording) and compare it
to wall-clock time at that instant - the difference is glass-to-glass
latency, given both devices' clocks are reasonably synced (NTP/chrony).
Off by default since it visibly stamps every frame.
