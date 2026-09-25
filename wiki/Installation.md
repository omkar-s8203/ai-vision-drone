# Installation

From a blank microSD card to the companion running as a service, plus the Android app. Wire the hardware first ([Hardware Setup](Hardware-Setup)).

## 1. Flash the OS

> Flashing erases the card. Double-check the selected device.

1. Install **Raspberry Pi Imager**.
2. Device **Raspberry Pi 5**; OS **Raspberry Pi OS Lite (64-bit)** (under "Raspberry Pi OS (other)"). No desktop is needed.
3. In advanced options (Ctrl+Shift+X) set: hostname (e.g. `aivisiondrone`), SSH on, username/password, Wi-Fi and country.
4. Write, insert, power on.

## 2. First boot

```bash
ssh <user>@<hostname>.local        # or the IP from your router
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

## 3. Camera and AI stack

```bash
sudo apt install -y imx500-all python3-picamera2 git tmux
rpicam-hello --list-cameras
```

## 4. Project and Python environment

```bash
git clone https://github.com/omkar-s8203/ai-vision-drone.git
cd ai-vision-drone
python3 -m venv --system-site-packages mavlink-venv
source mavlink-venv/bin/activate
pip install -e ".[video]"
```

- `--system-site-packages` is **required**: `picamera2` and `libcamera` come from apt and cannot be pip-installed.
- The venv name and location must match the `ExecStart` line of the systemd unit (step 7). The unit expects `~/ai-vision-drone/mavlink-venv`. (`INSTALL.md` in the repo uses `.venv` - either works, as long as the unit points at the right one.)
- `.[video]` installs aiortc/av for WebRTC; the core dependencies (pymavlink, pyserial, OpenCV headless, numpy, websockets, PyYAML) come from `pyproject.toml`.

Check the venv really sees the system packages:

```bash
grep include-system-site-packages mavlink-venv/pyvenv.cfg    # must say true
python -c "import picamera2; print('ok')"
```

## 5. Serial port and FC

Follow [Hardware Setup → Pi serial port](Hardware-Setup#pi-serial-port) and confirm a heartbeat.

## 6. First manual run

```bash
tmux new -s companion
cd ~/ai-vision-drone && source mavlink-venv/bin/activate
COMPANION_MODE=hardware python3 -m companion.main
```

Expect `Startup health check passed` and `server listening on 0.0.0.0:8765`. Detach with Ctrl+B then D. Note the Pi's IP with `hostname -I`.

If the health check fails, it lists every bad or missing config key at once - fix those first ([Configuration Reference](Configuration-Reference)).

## 7. Run as a service (systemd)

Stop the manual run first - only one process can hold the camera.

```bash
sudo cp deploy/ai-vision-drone.service /etc/systemd/system/
sudo nano /etc/systemd/system/ai-vision-drone.service    # check User, WorkingDirectory, ExecStart
sudo systemctl daemon-reload
sudo systemctl enable --now ai-vision-drone
```

Check it:

```bash
systemctl status ai-vision-drone
systemctl show ai-vision-drone -p Type -p WatchdogUSec -p ActiveState
#   Type=notify   WatchdogUSec=10s   ActiveState=active
journalctl -u ai-vision-drone -f
```

The unit is `Type=notify`. It only reaches `active` once the first camera frame has made it through the whole pipeline. If it sits in `activating` and restarts every 2 minutes, that "ready" signal is not arriving - read the journal. See [Running the Companion → The service](Running-the-Companion#the-service) for what the unit does.

## 8. Android app

1. Open `android/` in Android Studio and let Gradle sync (needs internet once).
2. Build and install onto the phone (or use the command line - see [Android Ground Station → Building](Android-Ground-Station#building)).
3. Join the phone to the Pi's Wi-Fi.
4. In **Settings**, enter the Pi's IP and port `8765`, tap Connect.

You should see `LINK: CONNECTED`, live video, detection boxes on anything the AI recognises, and real telemetry (not `--`) once the FC is wired.

## 9. Updating

A `git push` does not update the Pi or the phone. Update each.

**Pi:**

```bash
cd ~/ai-vision-drone
git pull
source mavlink-venv/bin/activate && pip install -e ".[video]"   # always - it is a no-op if nothing changed
sudo systemctl restart ai-vision-drone
journalctl -u ai-vision-drone -f
```

**When the systemd unit itself changed** (for example the move to `Type=notify` and the watchdog), copy it again and reload:

```bash
sudo cp deploy/ai-vision-drone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart ai-vision-drone
```

Config files under `companion/config/` update with `git pull`. A new required key that is missing stops boot with a clear message.

**Android:** `git pull`, then Run in Android Studio (or rebuild and `adb install -r`).

## Optional: better tracker for Teach mode

Stock `opencv-python-headless` only has the slow MIL tracker. The contrib build adds CSRT/KCF, used automatically. Install **inside the project venv**, never system-wide:

```bash
source ~/ai-vision-drone/mavlink-venv/bin/activate
which pip                                   # must be inside mavlink-venv
pip uninstall -y opencv-python-headless     # both provide cv2 - keep one
pip install opencv-contrib-python-headless
python -c "import cv2; print(hasattr(cv2, 'TrackerCSRT_create') or hasattr(cv2, 'legacy'))"
sudo systemctl restart ai-vision-drone
```
