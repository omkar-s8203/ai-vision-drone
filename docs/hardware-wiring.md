# Hardware Wiring & Power Budget

## Status

Pi 5 + AI Camera are set up and verified on a bench (not yet mounted on the
aircraft, not yet wired to the flight controller). Flight controller
wiring/power-source finalization/weight-and-thermal checks are still open -
see "Open items" below.

## Raspberry Pi OS setup (done)

- **OS**: Raspberry Pi OS Lite (64-bit), Debian trixie, kernel
  `6.18.50+rpt-rpi-2712` (aarch64).
- Flashed headless via Raspberry Pi Imager (hostname, SSH, WiFi configured
  in the imager's advanced options - no monitor/keyboard needed for setup).
- SSH: key-based access configured (password auth was used only for the
  initial `authorized_keys` install).
- Camera stack: `sudo apt install -y imx500-all python3-picamera2`.

## AI Camera (confirmed working)

- Sensor: Sony IMX500, registered by libcamera as
  `imx500@1a` on `/base/axi/pcie@1000120000/rp1/i2c@80000/imx500@1a`.
- Full sensor resolution: 4056x3040 (12MP) for stills;
  1280x720/640x480 configurable for the video/detection stream.
- **On-sensor object detection confirmed live**: model
  `/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk`
  (SSD MobileNetV2 FPN-Lite, 320x320 input, COCO-pretrained, on-sensor NMS).
  A person in frame produced `class=0 (person) score=0.73` via our own
  `companion.vision.camera.Picamera2IMX500Camera` +
  `companion.vision.detector.IMX500Detector` - not just a demo script.
- Available IMX500 models on this install (`/usr/share/imx500-models/`):
  object detectors (`ssd_mobilenetv2_fpnlite_320x320_pp`, `nanodet_plus_416x416_pp`,
  `efficientdet_lite0_pp`), classifiers (`mobilenet_v2`, `efficientnet_*`,
  `resnet18`, etc.), pose (`posenet`, `higherhrnet_coco`), segmentation
  (`deeplabv3plus`), and a passthrough (`inputtensoronly`) for custom models.

### Real API notes (learned the hard way - see the M2 fix commit)

The `picamera2.devices.IMX500` API differs from what general documentation
knowledge assumed before hardware existed to check against:

- Construct `IMX500(model_path)` (owns `camera_num`), then
  `Picamera2(imx500.camera_num)` - not a bare `Picamera2()`.
- Use `create_preview_configuration(...)` + `picam2.start(config, show_preview=False)`,
  not `create_video_configuration()` + separate `configure()`/`start()`.
- Get metadata via `picam2.capture_metadata()`, not
  `capture_request()` + `request.get_metadata()`.
- `imx500.get_outputs(metadata, add_batch=True)` returns
  `[boxes, scores, classes, count]` (or `None` on frames before the
  on-sensor network has produced its first result - normal for ~1s after
  `start()`, must not be treated as an error).
- `boxes` are normalized `(y0, x0, y1, x1)` per detection;
  `imx500.convert_inference_coords((y0, x0, y1, x1), metadata, picam2)`
  converts a box directly to pixel-space `(x, y, w, h)`.
- Class ids index directly into `imx500.network_intrinsics.labels`
  (90 entries, standard COCO categories) - no background-class offset.
- A 0.5 score threshold cleanly separates real detections from background
  noise in practice (confirmed: 0.73 for an actual person vs. 0.27-0.44 for
  spurious misclassifications of room background).

## Open items

- **Flight controller wiring**: not started. Plan calls for Pi UART
  (GPIO14/15) cross-wired to the FC's telemetry port (TELEM2 or similar),
  MAVLink 2 at 921600 baud - needs the actual FC model confirmed and a
  UART loopback/echo test before trusting it (docs plan M1/M7).
- **Power source**: Pi is currently bench-powered (USB-C), not yet running
  from a dedicated buck converter off the flight battery as planned - do
  not assume the drone's BEC can handle the added Pi 5 + camera load
  without measuring it first.
- **Mounting, weight, and CG impact**: not yet assessed.
- **Thermal**: not yet soak-tested under sustained AI+video load with a
  heatsink/fan fitted.
- **Rangefinder** (optional, M4): still an open decision, not purchased.
