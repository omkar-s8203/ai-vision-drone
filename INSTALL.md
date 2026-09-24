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
pip install -e ".[video]"
```

`--system-site-packages` is required - it lets the venv see the
apt-installed `picamera2`/`libcamera` bindings, which can't come from pip
(that's why `picamera2` is deliberately *not* in the `pip install` above -
see the `pi` extra in `pyproject.toml`, which exists for documentation but
isn't meant to be pip-installed on the Pi). Installing with `-e ".[video]"`
reads the dependency list straight from `pyproject.toml` (including
`opencv-python-headless`, needed for local video recording) instead of a
hand-typed list that can drift out of sync - see "Updating" below for why
this matters when you pull new changes.

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

## 7a. Auto-start on boot (systemd)

Once step 7 works manually, make it survive reboots and crashes instead of
needing a `tmux` session kept alive by hand:

```
sudo cp deploy/ai-vision-drone.service /etc/systemd/system/
sudo systemctl daemon-reload
```

**Before enabling it**, open `/etc/systemd/system/ai-vision-drone.service`
and check three lines actually match your setup:
```
User=omkar
WorkingDirectory=/home/omkar/ai-vision-drone
ExecStart=/home/omkar/ai-vision-drone/mavlink-venv/bin/python3 -m companion.main
```
The `ExecStart` path in particular must point at the **venv that was
actually created with `--system-site-packages`** (needed for `picamera2`) -
if you have more than one venv lying around, verify with:
```
grep include-system-site-packages /path/to/your/venv/pyvenv.cfg
```
(this exact mix-up - two differently-located venvs both literally named
the same thing, only one of them able to see `picamera2` - is a real
mistake made during this project's own bring-up; see
`docs/hardware-wiring.md` for the full story).

Then enable and start it:
```
sudo systemctl enable --now ai-vision-drone
sudo systemctl status ai-vision-drone
```
`status` should show `active (running)`. Watch its logs live with:
```
journalctl -u ai-vision-drone -f
```

If you were also running it manually in `tmux`, stop that session first
(`Ctrl+C` inside it) - the IMX500 camera can only be opened by one process
at a time, and the systemd-managed instance will otherwise fail to start
with a "Device or resource busy" error (see the troubleshooting table).

Common commands going forward:
```
sudo systemctl restart ai-vision-drone   # after a code update (see step 9)
sudo systemctl stop ai-vision-drone      # to free the camera for manual testing
sudo systemctl disable ai-vision-drone   # to stop it auto-starting on boot
```

## 8. Android Ground Station app

1. Open `android/` in Android Studio.
2. Let it sync (needs network access to Google's Maven/Maven Central).
3. Build and install onto your phone.
4. Make sure the phone is on the **same WiFi network** as the Pi.
5. In the app, enter the Pi's IP and port `8765`, tap Connect.

You should see: `Link: CONNECTED`, live camera video, live detection boxes
on anything the AI recognizes, and (once the FC is wired per step 5) real
telemetry in the top-right panel instead of `--` placeholders.

## 9. Updating after code changes

Whenever the code changes (a new feature, a bug fix, anything Claude Code
does in this repo gets committed and pushed to
`github.com/omkar-s8203/ai-vision-drone` on `master`), both the Pi and the
Android app need to be brought up to date separately - a `git push` from
the dev machine doesn't push to either of them automatically.

### Pi (companion code)

**If it's running under systemd** (step 7a):
```
cd ~/ai-vision-drone
git pull
pip install -e ".[video]"   # safe to always run - see note below
sudo systemctl restart ai-vision-drone
journalctl -u ai-vision-drone -f   # confirm it came back up cleanly
```
`pip install` needs to run as whichever user/venv the service uses (i.e.
with that venv active), not as root - activate it first, or call that
venv's `pip` by full path.

**If it's still running manually in the `tmux` session from step 7:**
```
tmux attach -t companion
# Ctrl+C to stop the running process
cd ~/ai-vision-drone
git pull
pip install -e ".[video]"
COMPANION_MODE=hardware python3 -m companion.main
```

`pip install -e ".[video]"` is safe to run every time even when nothing
changed - pip no-ops instantly if the installed versions already satisfy
`pyproject.toml`. Skipping it after a change that *did* add a dependency
(like `opencv-python-headless` was, for local video recording) is the
classic way to hit a confusing `ModuleNotFoundError` right after a pull -
just always run it. New/changed `.yaml` files under `companion/config/`
need no separate step - `git pull` updates them directly since they're
tracked files, not generated ones.

### Android app

The Android project lives in the same repo, so update it the same way,
then rebuild:

**Via Android Studio** (simplest): `git pull` (or let Android Studio's own
VCS pull do it), then hit **Run** - it rebuilds and reinstalls onto a
connected device/emulator in one step, and Gradle only recompiles files
that actually changed.

**Via command line**, if you have a JDK 17+ and an Android SDK installed
(check `android/local.properties` for `sdk.dir`, and
`android/gradle/wrapper/gradle-wrapper.properties` for the exact Gradle
version it expects):
```
cd android
git pull
./gradlew assembleDebug          # Linux/macOS
# or, from this Windows dev machine, the Gradle distribution used to build
# this project directly (see android/README.md for how it was located)
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.aivisiondrone.groundstation/.MainActivity
```

A build failure right after pulling a UI change is normal here - see
`android/README.md`'s "Fixed so far" list for the pattern of real errors
this project has hit (missing imports, deprecated APIs, version mismatches)
and how each was diagnosed from the actual Gradle error output.

## Troubleshooting quick reference

| Symptom | Likely cause |
|---|---|
| No heartbeat / zero bytes on `/dev/serial0` | Baud mismatch - try 57600 even if you set something else on the FC; verify with `cat /dev/serial0 \| od -An -tx1` for raw bytes before assuming wiring is wrong |
| `ModuleNotFoundError: No module named 'pymavlink'` (or similar) | The venv isn't activated in this shell - `source ~/ai-vision-drone/.venv/bin/activate` |
| `error: Multiple top-level packages discovered in a flat-layout` from `pip install -e` | Already fixed in this repo (`pyproject.toml`'s `[tool.setuptools.packages.find]`) - if you see this, `git pull` to get the fix |
| `ModuleNotFoundError: No module named 'picamera2'` even though `dpkg -l \| grep picamera2` shows it installed | Wrong venv active, or the active one wasn't created with `--system-site-packages`. Check with `echo $VIRTUAL_ENV` and `grep include-system-site-packages "$VIRTUAL_ENV/pyvenv.cfg"` - don't trust the `(name)` in your prompt if you have more than one venv sharing that name (see docs/hardware-wiring.md) |
| `Device or resource busy` from the IMX500 | Another process already has the camera open - check for a leftover `tmux` session (`tmux ls`), a running systemd service (`systemctl status ai-vision-drone`), or process (`pgrep -af companion.main`) - only one can hold the camera at a time |
| Pi freezes/red-LED-only under video load | Under-voltage - check power supply (need 5V/5A), run `vcgencmd get_throttled` (non-zero = a real power/thermal event was detected) |
| Video colors look wrong (blue-tinted) | Already fixed in this repo - `Picamera2IMX500Camera` requests `"RGB888"` specifically because picamera2's format names are inverted relative to actual channel order; if you see this, make sure you're on the latest `git pull` |
| AI detection shows zero boxes even for a clear, well-lit, close subject | Already fixed in this repo - `Picamera2IMX500Camera` previously called `capture_metadata()` and `capture_array()` as two separate captures per frame, which could desync which frame's metadata matched which frame's image, so `get_outputs()` never lined up with a frame that actually had inference results. Now uses a single `capture_request()` per frame. Make sure you're on the latest `git pull`; if it's still blank after that, check `journalctl -u ai-vision-drone -f` for `IMX500Detector`'s own rate-limited diagnostic warnings (distinguishes "on-sensor network never produced output" from "found candidates, but all below `score_threshold`") - see `docs/hardware-wiring.md` for the full three-pass debugging story |
| Can't reach the Pi's WebSocket from the phone | Confirm both are on the same WiFi network/subnet; a laptop building the Android app is not necessarily on the same network as the Pi |

See `docs/hardware-wiring.md` for the full story behind each of these (what
was tried, what the actual root cause turned out to be), `docs/protocol.md`
for the wire protocol, and `android/README.md` for Android-specific build
notes.

## Storage & maintenance

Two things accumulate under `~/ai-vision-drone-logs/` on the Pi over time:

- `sessions/*.jsonl` (structured event timeline, one file per run) -
  self-managing: `SessionRecorder` automatically prunes to the most recent
  50 sessions, oldest first, so this never fills the disk unattended.
- `recordings/*.mp4`/`.avi` (local video footage from the record button) -
  **not** auto-deleted, on purpose: unlike the session logs, this is
  footage the operator explicitly chose to capture, so nothing in this
  project ever deletes it without being asked. Offload/clear it manually
  (`scp` it off, or `rm ~/ai-vision-drone-logs/recordings/*` once copied)
  as part of routine field maintenance, especially before an extended
  video-recording session on a full SD card.

## Optional: better tracker for Teach mode

Teach mode (`docs/teach-and-train.md`) tracks taught objects with an OpenCV tracker. The
plain `opencv-python-headless` this project depends on only has the MIL tracker; the
contrib build adds CSRT/KCF, which are used automatically when present.

**Install it inside the project's virtual environment, not system-wide** - Raspberry Pi OS
refuses system-wide `pip install` (`externally-managed-environment`), and
`--break-system-packages` can break the OS's own Python. Use the same venv as the systemd
service (see `deploy/ai-vision-drone.service`; step 4 above):

```
cd ~/ai-vision-drone
source mavlink-venv/bin/activate
which pip        # must be .../ai-vision-drone/mavlink-venv/bin/pip
pip uninstall -y opencv-python-headless    # both provide `cv2`; keep only one
pip install opencv-contrib-python-headless
python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'TrackerCSRT_create') or hasattr(cv2, 'legacy'))"
sudo systemctl restart ai-vision-drone
```

The last value should print `True`; if `False`, Teach mode still works with the slower MIL
tracker. Measure fps with a taught object on the Pi (lab checklist 6D.3) before relying on it.
