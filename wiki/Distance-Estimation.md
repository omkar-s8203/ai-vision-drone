# Distance Estimation

Follow's forward/back speed, Orbit's radius and the obstacle check all depend on how far away an object is. The estimate comes from one camera (a pinhole model), optionally replaced by a rangefinder for the tracked target. Code: `companion/guidance/distance.py`.

## The pinhole estimate

```
distance = real_size × focal_length_px / size_in_pixels
```

Known real sizes:

| Class | Width | Height |
|---|---|---|
| person | 0.5 m | **1.7 m** |
| car | 1.8 m | - |
| truck | 2.3 m | - |
| bicycle | 0.6 m | - |
| motorcycle | 0.8 m | - |
| taught objects | as entered by the operator | as entered |

Other classes have no distance.

### Rules for Follow and Orbit (steady, not jumpy)

- An **upright person** (box height ≥ 1.2 × width) uses **height** with `fy`. Width swings 2-3x with pose and facing; height barely moves.
- A box **clipped by the image border** in the measured dimension is refused, because a clipped box reads as further away than reality and Follow would close in. The other dimension is used if intact; otherwise distance is unknown.
- **Unknown distance → Follow holds forward speed at zero** instead of guessing.
- The target's distance passes through `DistanceFilter`: median of the last 3 readings, then exponential smoothing (α 0.5). Samples older than 1 s are dropped. The filter resets when the target changes.
- When the target was not seen on this frame, the last filtered value is reused rather than feeding the same old box into the filter again.

### Rule for the obstacle check (conservative)

The proximity check deliberately uses the **width** estimate: arms out or side-on reads closer, never further, which is the safe direction for "something is too close".

## Calibration

`companion/config/camera_calibration.yaml` holds `fx`, `fy`, `cx`, `cy` at 1280x720. **The current values are placeholders (fx = fy = 900) - the camera has never been calibrated.** Do it before trusting Follow's separation, Orbit's radius or obstacle distances:

```bash
sudo systemctl stop ai-vision-drone
# take 15-25 photos of a PRINTED checkerboard from varied angles at 1280x720
python tools/calibrate_camera.py --images "calib_photos/*.jpg" --board-cols 9 --board-rows 6
sudo systemctl start ai-vision-drone
```

Tips from two failed attempts: use a **printed** board (a screen causes glare, moiré and dead space), count **inner** corners correctly, use bright light, and avoid motion blur.

The boot check refuses to start if the calibration resolution differs from the camera resolution.

## Validating accuracy

The target is **< 15 % error between 3 and 15 m** (lab checklist 6B: 3, 5, 8, 12 m, tape-measured).

```bash
python tools/distance_validation.py --template > measurements.json
# fill in the detector's box size at each measured distance
python tools/distance_validation.py measurements.json
```

First real data point: a person at 2 m read 1.9-2.0 m even with placeholder intrinsics. That is encouraging but not yet the acceptance test.

## Rangefinder

With `rangefinder.enabled: true`, a Benewake TFmini-S becomes the distance source **for the tracked target only** (matched by class and overlap), never for other objects in frame. See [Hardware Setup](Hardware-Setup#optional-rangefinder-tfmini-s). Not yet bought or wired.
