# Hardware Wiring & Power Budget

## Status

Pi 5 + AI Camera + flight controller (Cube Orange, TELEM1) are all wired up
and confirmed working together on a bench (not yet mounted on the
aircraft). Power-source finalization for flight and weight/thermal checks
are still open - see "Open items" below.

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

## Video streaming (confirmed working, real hardware)

Real camera video (not the sim's synthetic rectangle) streamed live over
WebRTC to a real Android phone, through our own `AiortcVideoPipeline` and
`Picamera2IMX500Camera.get_latest_frame()`. Two real bugs found and fixed
along the way:

- **Inverted color channels**: picamera2's stream format names are inverted
  relative to the numpy channel order they actually produce. Requesting
  `"BGR888"` produced a visibly wrong (red/blue swapped, blue-tinted) feed
  once piped through `PyAV`'s `VideoFrame.from_ndarray(array, format="bgr24")`.
  Requesting `"RGB888"` is what actually yields BGR-ordered array data -
  fixed in `Picamera2IMX500Camera` accordingly.
- **`SessionRecorder` pointed at `/var/log/...`**, which a non-root user
  can't write to - moved to `~/ai-vision-drone-logs`.

### Power supply is not optional - confirmed by a real crash

Running the camera + on-sensor AI + **software** video encoding
(`aiortc`'s CPU-based encode path - the "quick bringup" pipeline, not the
planned GStreamer hardware-encode one) together is a real CPU/power load.
Powering the Pi 5 from a **laptop USB port** caused a hard freeze a few
seconds into video streaming (red power LED on, everything else
unresponsive - classic under-voltage brownout signature). Switching to a
proper wall charger resolved it (`vcgencmd get_throttled` read `0x0`,
clean, afterward). **Do not power the Pi 5 from a laptop/phone USB port for
anything beyond bench camera-only testing** - use a supply rated at least
5V/5A (the official 27W USB-C supply), and get a heatsink/fan before more
sustained video-mode testing - none is fitted yet and this hasn't been
soak-tested.

**Never connect a flight controller's TELEM port VCC (5V) pin to the Pi**
to try to power it - it happened once during wiring (immediately corrected).
The TELEM port's regulator is sized for a small accessory, not a Raspberry
Pi 5; back-feeding this way risks damaging the flight controller's power
regulation, not just the Pi.

## Flight controller wiring (confirmed working)

- **FC**: CubePilot Cube Orange, wired via carrier board **TELEM1**.
- Wiring (matches CubePilot's own documented TELEM pinout exactly):
  ```
  Cube TELEM1 TX  -> Pi GPIO15 (physical pin 10, UART RX)
  Cube TELEM1 RX  -> Pi GPIO14 (physical pin 8, UART TX)
  Cube TELEM1 GND -> Pi GND
  ```
- Pi side: UART enabled via `raspi-config` (Interface Options -> Serial ->
  no login shell, yes hardware); `dtparam=uart0=on` in
  `/boot/firmware/config.txt`. `/dev/serial0` symlinks to `ttyAMA10`
  (Pi 5's RP1-chip UART naming - differs from the `ttyAMA0` older Pi models
  use, but is the correct GPIO14/15 UART here, confirmed via `pinctrl`).
- **Baud rate is 57600, not 921600.** This was the actual root cause of a
  very long debugging session: Mission Planner's parameter list *displayed*
  `SERIAL1_BAUD = 921` (921600) after setting and writing it, but the FC
  never actually adopted it - it kept running TELEM1 at ArduPilot's default
  57600 regardless of what the GCS UI showed. Every test at 921600 baud
  (raw `cat`/`od` byte dumps, `pymavlink.wait_heartbeat()`, MAVProxy) failed
  identically because of this mismatch alone - wiring, GND, Pi UART
  enablement, pin muxing, permissions, and the Bluetooth/UART conflict fix
  below were all independently confirmed correct throughout and were never
  the problem. **Lesson: when a GCS-displayed parameter and observed FC
  behavior disagree, trust the behavior** - verify with a baud sweep
  (57600 is ArduPilot's TELEM default) rather than assuming a UI-displayed
  value was actually applied.
- **Found and fixed along the way**: Pi 5 Bluetooth was claiming the UART
  (`hci_uart_bcm` in `dmesg`) - fixed with `dtoverlay=disable-bt` in
  `/boot/firmware/config.txt` plus `sudo systemctl disable bluetooth`.
  Also needed `pip install pyserial` (a real missing dependency - see
  pyproject.toml; pymavlink only imports it lazily for real serial
  connections, so sim-mode's UDP-only tests never caught this) and
  `pip install future` (a missing MAVProxy dependency).
- **Confirmed working**: `pymavlink.mavlink_connection('/dev/serial0', baud=57600)`
  successfully receives a heartbeat (system 1) and continuous `ATTITUDE`
  messages at 10 Hz when requested. `companion/config/hardware.yaml`
  updated to `baud: 57600` to match.
- Common mistakes made and corrected along the way, worth remembering for
  next time: "physical pin N" vs "GPIO N" are different numbering schemes
  on the 40-pin header - always double-check against the official pinout
  diagram, not just the BCM GPIO number. A `pinctrl`-based loopback test
  (toggle one GPIO, read another) is only meaningful when nothing else is
  connected to either pin - it's not a valid test once a real device (like
  the FC) is already wired to those same pins, since the two signals are
  then expected to be independent, not correlated.

## Open items

- **Power source for flight**: Pi is currently bench-powered from a wall
  charger, not yet running from a dedicated buck converter off the flight
  battery as planned - do not assume the drone's BEC can handle the added
  Pi 5 + camera load without measuring it first.
- **Mounting, weight, and CG impact**: not yet assessed.
- **Thermal**: no heatsink/fan fitted yet; not soak-tested under sustained
  AI+video load even with adequate power.
- **Rangefinder** (optional, M4): still an open decision, not purchased.
