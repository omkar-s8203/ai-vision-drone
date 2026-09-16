# Installation Guide

Complete setup, from a blank microSD card to a working camera + AI + video +
MAVLink pipeline. This consolidates everything learned during real hardware
bring-up (see `docs/hardware-wiring.md` for the full debugging history
behind some of these steps, if you're curious why they're done this way).

## What you need

- Raspberry Pi 5 (8GB recommended)
- Raspberry Pi AI Camera (Sony IMX500)
- A flight controller running ArduPilot with a free TELEM UART port
  (tested against a CubePilot Cube Orange)
- microSD card, 32GB+, A2-rated if possible
- **A proper 5V/5A USB-C power supply for the Pi** (see "Power supply" below
  - this is not optional, a laptop/phone USB port is not enough)
- A heatsink/fan for the Pi 5 (recommended before sustained video streaming)
- An Android phone (API 26+) for the Ground Station app
- A computer to flash the SD card and build the Android app

---

## 1. Flash the OS

**⚠️ This erases the target microSD card - double-check the selected device
in the imager before writing.**

1. Install **Raspberry Pi Imager** (`raspberrypi.com/software`).
2. Device: **Raspberry Pi 5**. OS: **Raspberry Pi OS (other) → Raspberry Pi
   OS Lite (64-bit)** - no desktop needed, this runs headless.
3. Before writing, open advanced options (gear icon / Ctrl+Shift+X) and
   configure it headless:
   - Hostname (e.g. `aivisiondrone`)
   - Enable SSH (password auth is fine to start)
   - Username/password
   - WiFi SSID/password + country code
4. Write, then move the card to the Pi and power it on.

## 2. First boot and SSH

```
ssh <username>@<hostname>.local
```
(fall back to the IP from your router's client list if `.local` doesn't
resolve). Then update the system:

```
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

## 3. Camera / AI stack

```
sudo apt install -y imx500-all python3-picamera2 git tmux
```

Verify the camera is detected:
```
rpicam-hello --list-cameras
```

## 4. Clone the project and set up Python

```
git clone https://github.com/omkar-s8203/ai-vision-drone.git
cd ai-vision-drone
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install pymavlink pyserial websockets pyyaml numpy aiortc av future
```

`--system-site-packages` is required - it lets the venv see the
apt-installed `picamera2`/`libcamera` bindings, which can't come from pip.

## 5. Flight controller wiring (MAVLink)

Wire the FC's TELEM port to the Pi's UART, **crossed**:

```
FC TELEM TX  -> Pi GPIO15 (physical pin 10, UART RX)
FC TELEM RX  -> Pi GPIO14 (physical pin 8, UART TX)
FC TELEM GND -> Pi GND (e.g. physical pin 6)
```

Never connect the TELEM port's VCC (5V) pin to anything on the Pi - it's
sized for a small accessory, not a Raspberry Pi 5, and back-feeding risks
damaging the FC's power regulation.

**On the FC** (via Mission Planner/QGroundControl), set the matching serial
port's protocol and baud, e.g. for TELEM1 (`SERIAL1`):
```
SERIAL1_PROTOCOL = 2      (MAVLink2)
SERIAL1_BAUD = 57         (57600 - ArduPilot's TELEM default; don't assume
                            a different value you set actually "took" -
                            verify empirically, see docs/hardware-wiring.md)
```
Write params and reboot the FC.

**On the Pi**, enable the UART:
```
sudo raspi-config
```
Interface Options → Serial Port → "login shell over serial?" **No** →
"enable serial port hardware?" **Yes** → reboot.

**Pi 5-specific fix**: Bluetooth can claim the same UART. If MAVLink doesn't
work after the above, add this and disable Bluetooth:
```
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
sudo systemctl disable bluetooth
sudo reboot
```

**Verify** (from the repo root, venv active):
```
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('/dev/serial0', baud=57600)
print('Waiting for heartbeat...')
print('Got heartbeat:', conn.wait_heartbeat(timeout=10))
"
```

## 6. Power supply

Run the camera + on-sensor AI + video encoding together and the Pi 5 draws
real current under load. A laptop/phone USB port is **not** sufficient and
will brown out mid-stream. Use a supply rated **5V/5A** (the official 27W
USB-C supply). Fit a heatsink/fan before sustained video-mode testing.

## 7. Run the companion stack

Use `tmux` so it survives SSH disconnects:
```
tmux new -s companion
cd ~/ai-vision-drone
source .venv/bin/activate
COMPANION_MODE=hardware python3 -m companion.main
```
Detach with `Ctrl+B` then `D`; reattach later with `tmux attach -t companion`.

You should see `server listening on 0.0.0.0:8765` with no errors. Note the
Pi's IP (`hostname -I`) - you'll need it for the Android app.

## 8. Android Ground Station app

1. Open `android/` in Android Studio.
2. Let it sync (needs network access to Google's Maven/Maven Central).
3. Build and install onto your phone.
4. Make sure the phone is on the **same WiFi network** as the Pi.
5. In the app, enter the Pi's IP and port `8765`, tap Connect.

You should see: `Link: CONNECTED`, live camera video, live detection boxes
on anything the AI recognizes, and (once the FC is wired per step 5) real
telemetry in the top-right panel instead of `--` placeholders.

## Troubleshooting quick reference

| Symptom | Likely cause |
|---|---|
| No heartbeat / zero bytes on `/dev/serial0` | Baud mismatch - try 57600 even if you set something else on the FC; verify with `cat /dev/serial0 \| od -An -tx1` for raw bytes before assuming wiring is wrong |
| `ModuleNotFoundError: No module named 'pymavlink'` (or similar) | The venv isn't activated in this shell - `source ~/ai-vision-drone/.venv/bin/activate` |
| `Device or resource busy` from the IMX500 | Another process already has the camera open - check for a leftover `tmux` session (`tmux ls`) or process (`pgrep -af companion.main`) |
| Pi freezes/red-LED-only under video load | Under-voltage - check power supply (need 5V/5A), run `vcgencmd get_throttled` (non-zero = a real power/thermal event was detected) |
| Video colors look wrong (blue-tinted) | Already fixed in this repo - `Picamera2IMX500Camera` requests `"RGB888"` specifically because picamera2's format names are inverted relative to actual channel order; if you see this, make sure you're on the latest `git pull` |
| Can't reach the Pi's WebSocket from the phone | Confirm both are on the same WiFi network/subnet; a laptop building the Android app is not necessarily on the same network as the Pi |

See `docs/hardware-wiring.md` for the full story behind each of these (what
was tried, what the actual root cause turned out to be), `docs/protocol.md`
for the wire protocol, and `android/README.md` for Android-specific build
notes.
