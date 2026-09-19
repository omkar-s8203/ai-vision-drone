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
