# Tools

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

## `imx500_convert.py` (not yet implemented)

Planned: a wrapper around Sony's imx500-converter toolchain for deploying
custom-trained models to the Raspberry Pi AI Camera (M2) - only needed if
a required object class isn't covered by the stock COCO model.

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

`analyze` reports: detection rate, the longest run of consecutive
zero-detection frames (the key regression signal - a sudden long gap where
there previously wasn't one), detection-score stability, and bounding-box
position jitter frame-to-frame. Also doubles as real data for tuning
`camera.score_threshold` (`hardware.yaml`) against actual score
distributions instead of leaving it as an untuned guess.

**Not yet run against real hardware** - `analyze_session()` (the actual
stability math) is unit-tested against a synthetic session file
(`companion/tests/test_detection_regression.py`); `capture` needs the real
Pi and camera. Once a first real session is captured, save it (e.g. as
`tools/reference_sessions/baseline.json`) and re-run `analyze` against a
fresh capture after any future change to the detection/camera pipeline to
compare against it by eye - there's no automated pass/fail threshold for
drift between two sessions yet (jitter/score distributions will
legitimately vary session to session with lighting/distance/subject), just
the tool to make that comparison possible.
