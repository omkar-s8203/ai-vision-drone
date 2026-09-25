# Hardware Bring-Up Lessons

Real problems found while bringing the system up on the Pi, flight controller and camera, and how each was actually solved. The full narratives are in `docs/hardware-wiring.md` and the milestone notes in the README.

## The baud rate that never changed

**Symptom:** no MAVLink at all - raw byte dumps, `wait_heartbeat()` and MAVProxy all failed at 921600 baud.

**What it was not:** wiring, ground, the Pi UART, pin muxing, permissions, the Bluetooth conflict - each was independently checked and was fine.

**Cause:** Mission Planner *displayed* `SERIAL1_BAUD = 921` after writing it, but the Cube Orange kept running TELEM1 at ArduPilot's default **57600**.

**Lesson:** when a GCS-displayed parameter and observed behaviour disagree, trust the behaviour. Sweep baud rates (57600 first) before blaming wiring.

## Zero detections: the capture_request fix

**Symptom:** weeks after detection had worked, a clear, close, well-lit subject produced no boxes. The detector logged `outputs=None` on every frame.

It took three passes, each checked with a standalone diagnostic script on the Pi:

1. **The firmware wait was missing.** The on-sensor network's firmware upload is separate from opening the camera; nothing waited for it. Added `show_network_fw_progress_bar()`. *Did not fix it.*
2. **The wait was in the wrong place.** The upload only begins after `configure()`, and the wait was before it, so it returned instantly. Reordered to `configure()` → wait → `start()`. The upload now completed in ~3 s. *Still no detections.*
3. **Two captures per frame.** The loop called `capture_metadata()` and `capture_array()` separately - two independent captures that can land on different sensor frames, so the AI output never lined up with the image. **One `capture_request()` per frame** (metadata and image from the same request) fixed it: a real detection at frame 2.

A `sudo apt full-upgrade` in between (newer libcamera) had probably changed timing enough to expose the latent bugs.

**Lesson:** prove each hypothesis with a minimal, independent script against the real device before shipping a "fix".

## Blue-tinted video

picamera2's format names are inverted relative to numpy channel order. Requesting `"BGR888"` gave red/blue swapped video; requesting **`"RGB888"`** yields the BGR array the encoder expects.

## 30 FPS configured, 15 FPS delivered

`capture_request()` already blocks until the next frame at the hardware frame rate - it *is* the pacing. The loop also slept a full frame period afterwards, halving throughput. Removing the sleep restored ~30 FPS. Do not add a sleep back.

## Laptop USB power crashes the Pi

Camera + on-sensor AI + software video encoding froze the Pi a few seconds into streaming when powered from a laptop port (red LED only - brown-out). A proper 5 V / 5 A supply fixed it (`vcgencmd get_throttled` = `0x0`). Never power the Pi from the FC's TELEM 5 V pin either - it happened once during wiring and was corrected immediately.

## The venv that could not see picamera2

Two different venvs were both named `mavlink-venv` - one inside the project (created with `--system-site-packages`) and one in the home folder (without). The prompt showed `(mavlink-venv)` for both, so `ModuleNotFoundError: picamera2` looked like a broken system install. Comparing `sys.prefix` and each `pyvenv.cfg` found it.

**Lesson:** check `echo $VIRTUAL_ENV` before assuming a system package is broken. The systemd unit pins an absolute venv path for this reason.

## pip install silently did nothing

`pip install -e ".[video]"` failed with "Multiple top-level packages discovered" (`companion/`, `sim/`, `android/`), so nothing was installed and later imports failed one screen further down. Fixed with an explicit `[tool.setuptools.packages.find] include = ["companion*"]`. `pyserial` was also missing (pymavlink imports it lazily only for serial links, so UDP-only sim tests never caught it).

## Link OK, but all telemetry `--`

The FC sent heartbeats (so mode and armed state were right) but nothing else. ArduPilot only streams other messages to a link that asks for them, as a GCS does on connect. The bridge now sends `REQUEST_DATA_STREAM` on the first heartbeat, and again whenever position goes stale (for example after an FC reboot).

## The score threshold

A real capture at 0.5 confidence showed a 36 % detection rate and a 2.2 s dropout, while real people scored 0.44 and 0.32. At **0.35** the detection rate rose to 49 % and the longest dropout fell to 0.26 s.

## DISARM does nothing

ArduCopter refuses a normal disarm while its land detector thinks it is flying - props spinning on the bench can trip that. The fix was a separate **Force disarm** (param2 = 21196), never used for arming, and now refused above 1.5 m.

## Camera calibration attempts

Two attempts found 0 corners: first a board-size mismatch (count **inner** corners), then image quality - low light, blur, a small on-screen board with glare and window chrome. Use a **printed** board in bright light. Calibration is still outstanding.

## Pi 5 specifics

- `/dev/serial0` → `ttyAMA10` (not `ttyAMA0`).
- Bluetooth can hold the UART: `dtoverlay=disable-bt` and disable the service.
- "Physical pin N" and "GPIO N" are different numberings. A `pinctrl` loopback test is only valid with nothing else attached to those pins.
