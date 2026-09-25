# Vision and Detection

## On-sensor AI

The Raspberry Pi AI Camera's Sony IMX500 runs the neural network **on the camera chip**. Every frame arrives with the image *and* the model's output attached, so the Pi's CPU does almost no detection work.

| | |
|---|---|
| Default model | `imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk` - SSD MobileNetV2 FPN-Lite, 320x320 input, COCO-trained, NMS on the sensor |
| Classes | 90 COCO labels, indexed directly (no background offset) |
| Stream | 1280x720 @ 30 FPS |
| Measured on the Pi | **27.1 FPS**, 0.3 ms p95 parse latency, ~12 % CPU (all inside the plan's targets: ≥15 FPS, <60 ms, <15 %) |

Code: `companion/vision/camera.py` (`Picamera2IMX500Camera`), `companion/vision/detector.py` (`IMX500Detector`).

## Capturing a frame

Each frame comes from **one** `capture_request()`. The metadata (which carries the AI output) and the image come from the same sensor frame. Two separate calls (`capture_metadata()` then `capture_array()`) can land on different frames, and then the AI output never lines up - that bug once caused zero detections for weeks ([story](Hardware-Bring-Up-Lessons#zero-detections-the-capture_request-fix)).

Start-up order matters: `configure()` → wait for the network firmware upload (`show_network_fw_progress_bar()`) → `start()`. The firmware upload only begins after `configure()`.

The capture runs on a **dedicated daemon thread**. The event loop receives only the newest frame, so if processing falls behind, older frames are dropped instead of piling up latency.

### Camera stall detection

If no frame arrives for `camera.stall_timeout_s` (**2 s**; 15 s for the very first frame, while the AI firmware loads), or the capture raises, the camera raises `CameraStallError`. The companion logs it and exits with **status 3**, and systemd restarts it in IDLE. A hung libcamera call cannot be cancelled in-process, which is why this restarts instead of retrying. See [Safety Architecture → Process recovery](Safety-Architecture#process-and-link-recovery).

### Colour order

picamera2's format names are inverted relative to numpy channel order: requesting `"RGB888"` yields **BGR** data, which is what the video pipeline expects. `"BGR888"` gives a blue-tinted picture.

## Parsing detections

`IMX500Detector.parse()` turns the model output into `Detection` objects (pixel box, score, class id and name, frame time):

- Boxes come out normalised; `imx500.convert_inference_coords()` converts them to pixels.
- Box coordinate order is `yx` (`y0, x0, y1, x1`) for the stock model. A retrained model may emit `xy` - set `camera.bbox_order`. A wrong order looks plausible but is wrong.
- Scores below `camera.score_threshold` (**0.35**) are dropped.
- NaN, infinite or degenerate (≤1 px) boxes are dropped.
- A retrained model's class names come from `camera.labels_path` (one per line, in class-index order).

### Why the threshold is 0.35

A real 812-frame capture at the old 0.5 threshold showed only a 36 % detection rate and a 2.2 s dropout. Real people were scoring 0.44 and 0.32. At 0.35 the detection rate rose to 49 % and the longest dropout fell to 0.26 s. When detection does pass, confidence is solid (0.76 mean). Raise it back toward 0.5 if false positives appear.

## Frames without an AI result

The IMX500 does not attach a result to every frame: every frame for about 1 s after start, and intermittently afterwards. `parse()` therefore has **three** outcomes:

| Returns | Meaning |
|---|---|
| a non-empty list | The model ran and found these objects |
| `[]` | The model ran and saw **nothing** - the target really is gone |
| `None` | This frame carries **no AI result** - the target may be right there |

Before this distinction, a result-less frame looked like "nothing seen". The tracker counted a miss, Follow held for that frame, and the drone stuttered and the app's boxes blinked. Now the orchestrator (`_detections_for()` in `companion/main.py`):

1. On `None`, reuses the **last real detections** for up to `detection_carry_max_s` (**0.5 s**). They feed the app's boxes, the obstacle check, and the detection list.
2. Does **not** update the tracker on those frames (`coast()`), and skips the identity check and the appearance re-lock. Those compare boxes to the *current* image, and a carried box is from an older one.
3. Waits for a fresh result before applying an operator tap, so a tap never locks onto an old box.
4. After 0.5 s with no AI result at all, treats frames as "saw nothing" (`[]`), so an AI that has stopped degrades to "target lost" instead of frozen tracking.

The rate-limited journal line `IMX500Detector: outputs is None` is normal in moderation. If it logs constantly and no boxes ever appear, the network is not running (check the model path and firmware).

## Other detectors

`PassthroughDetector` is used in sim mode: the "raw" output is already a list of `Detection` objects (or `None` to simulate a result-less frame).

## Performance tools

- `tools/benchmark_detection.py` - FPS, latency and CPU against the M2 targets.
- `tools/detection_regression.py` - records a live session's detections and reports detection rate, longest dropout, score and box jitter, plus tracking reacquisition.

See [Tools](Tools).
