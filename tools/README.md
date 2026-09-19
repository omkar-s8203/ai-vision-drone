# Tools

## `calibrate_camera.py` (confirmed against real hardware - see caveat below)

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

**Now run for real** against real checkerboard photos taken with the
actual Pi camera, producing real fitted intrinsics on the Pi. Originally
built and tested on this dev machine (which has no camera of its own) via
unit tests of the file-globbing/corner-detection/validation logic and a
manual end-to-end CLI smoke test with synthetic multi-view checkerboard
images - those still pass and remain the test coverage for the tool's own
logic; the real-photo run is what confirmed the tool against actual
hardware.

**Not yet committed to this repository**: `git log` shows
`companion/config/camera_calibration.yaml` unchanged since the very first
commit that created it - the placeholder `fx=900.0`/`fy=900.0`/etc. values
are still what's checked in. The real fitted values from the Pi's
calibration run only exist on the Pi's local filesystem right now. Until
they're committed and pushed, a fresh `git clone`/`git pull` (e.g. onto a
replacement Pi, or by anyone else working from this repo) gets the
placeholder config back, silently undoing the calibration. Run
`git add companion/config/camera_calibration.yaml && git commit && git
push` **on the Pi itself** (it already has the real file) to fix this.

## `imx500_convert.py` (not yet implemented)

Planned: a wrapper around Sony's imx500-converter toolchain for deploying
custom-trained models to the Raspberry Pi AI Camera (M2) - only needed if
a required object class isn't covered by the stock COCO model.
