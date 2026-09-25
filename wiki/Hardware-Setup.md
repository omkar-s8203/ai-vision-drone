# Hardware Setup

## Parts

| Part | Notes |
|---|---|
| Raspberry Pi 5 (8 GB recommended) | Runs the companion stack. Fit a **heatsink/fan** before sustained video work. |
| Raspberry Pi AI Camera (Sony IMX500) | Runs detection on the sensor itself. |
| ArduPilot flight controller with a free TELEM UART | Tested on a **CubePilot Cube Orange** via TELEM1. |
| 5 V / 5 A power supply | The official 27 W USB-C supply on the bench. For flight, a dedicated buck converter off the flight battery (not yet done - measure before trusting the drone's BEC). |
| microSD card, 32 GB+, A2-rated | Raspberry Pi OS Lite 64-bit. |
| RC transmitter + receiver | Needs a spare 2- or 3-position switch for `FLTMODE_CH`. |
| Android phone, API 26+ | Runs the Ground Station app. |
| Optional: Benewake TFmini-S | Rangefinder for more accurate target distance. Driver written, not yet bought or wired. |

## Flight controller wiring (MAVLink)

Wire the FC's TELEM port to the Pi's UART, **TX to RX crossed**:

```
FC TELEM TX   ->  Pi GPIO15  (physical pin 10, UART RX)
FC TELEM RX   ->  Pi GPIO14  (physical pin 8,  UART TX)
FC TELEM GND  ->  Pi GND     (e.g. physical pin 6)
```

> **Never connect the TELEM port's 5 V pin to the Pi.** The TELEM regulator is sized for a small accessory. Back-feeding a Pi 5 through it can damage the flight controller's power regulation.

"Physical pin N" and "GPIO N" are different numbering schemes on the 40-pin header - check against the official pinout.

### Flight controller parameters

Set with Mission Planner or QGroundControl over USB, then write and reboot the FC:

| Parameter | Value | Why |
|---|---|---|
| `SERIAL1_PROTOCOL` | `2` (MAVLink2) | TELEM1 talks MAVLink to the Pi |
| `SERIAL1_BAUD` | `57` (57600) | Must match `hardware.yaml` `mavlink.baud`. **Verify the FC actually uses it** - see [Hardware Bring-Up Lessons](Hardware-Bring-Up-Lessons#the-baud-rate-that-never-changed) |
| `FLTMODE_CH` | your spare switch's channel | The hardware override. See [Lab Testing](Lab-Testing-and-Flight-Readiness#stages) |
| `FLTMODE1`-`FLTMODE6` | at least one position `GUIDED`, at least one `LOITER` or `STABILIZE` | The Pi only guides in `GUIDED` |
| `GUID_TIMEOUT` | known value (default 3 s) | What stops the aircraft if the Pi dies |
| `FENCE_ENABLE`, `FENCE_TYPE`, `FENCE_RADIUS`, `FENCE_ALT_MAX`, `FENCE_ACTION` | enabled, RTL (or Brake/Land) | Geofence |
| `BATT_MONITOR`, `BATT_CAPACITY`, low/critical voltage or mAh, `BATT_FS_LOW_ACT`, `BATT_FS_CRT_ACT` | monitor on; low = RTL, critical = LAND or RTL | Battery failsafe. The app must show battery %, or the Pi's battery gates cannot work |
| `FS_THR_ENABLE` | enabled, RTL/Land | Radio failsafe |
| `RTL_ALT` | right for the site | RTL flies a straight line at this height |

Save the full `.param` file next to your lab-test record.

### Pi serial port

```bash
sudo raspi-config
# Interface Options -> Serial Port -> login shell over serial? No -> serial hardware? Yes
```

On the Pi 5, Bluetooth can claim the same UART. If MAVLink stays silent:

```bash
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
sudo systemctl disable bluetooth
sudo reboot
```

`/dev/serial0` points at `ttyAMA10` on the Pi 5 (not `ttyAMA0` as on older models) - that is correct.

Verify a heartbeat arrives:

```bash
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('/dev/serial0', baud=57600)
print('Got heartbeat:', conn.wait_heartbeat(timeout=10))
"
```

## Camera

Plug the AI Camera into a CSI port with the Pi **powered off**. Never hot-plug the ribbon cable.

```bash
sudo apt install -y imx500-all python3-picamera2
rpicam-hello --list-cameras     # should list imx500
```

Models live in `/usr/share/imx500-models/`. The project uses `imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk`. Others are available (NanoDet, EfficientDet, classifiers, pose, segmentation) but are not wired in.

Resolution runs at 1280x720 @ 30 FPS for video and detection. The camera must be **calibrated at that resolution**; the boot check refuses to start if `camera_calibration.yaml` and `hardware.yaml` disagree.

## Power

The camera, on-sensor AI and software video encoding together are a real load:

- A **laptop USB port is not enough**. It caused a hard freeze a few seconds into streaming (red LED only - a brown-out).
- Use a supply rated **5 V / 5 A**. Check `vcgencmd get_throttled` reads `0x0` after a session; anything else means an under-voltage or thermal event.
- For flight, feed the Pi from a dedicated 5 V / 5 A buck converter off the flight battery. Do not assume the aircraft's BEC can carry the extra load without measuring it.

## Optional rangefinder (TFmini-S)

Driver: `companion/guidance/rangefinder.py`. It parses the 9-byte frame, rejects weak-signal and out-of-range readings, and resyncs after corrupted bytes. Enable it in `hardware.yaml`:

```yaml
rangefinder:
  enabled: true
  port: /dev/serial1
  baud: 115200
```

A rangefinder reading is only applied to the tracked target (matched by class and overlap), never to other objects in frame.

## Open hardware items

- Flight power source (still bench-powered).
- Weight / centre-of-gravity impact of the mounted Pi and camera.
- Thermal soak with the heatsink fitted, in the mounted configuration.
- Rangefinder purchase (optional).
