# Troubleshooting

Start with the logs: `journalctl -u ai-vision-drone -f` (the Pi's own lines) and `python tools/live_monitor.py --uri ws://<pi-ip>:8765` (what the app receives).

## Start-up

| Symptom | Cause and fix |
|---|---|
| `Startup health check failed - refusing to start` | A config key is missing or out of range. The message lists every problem - fix those in `companion/config/*.yaml`. After a `git pull` that added keys, make sure your local edits did not drop them. |
| `camera_calibration.yaml: image_width=... does not match` | Calibrate at the running resolution, or set the camera back to 1280x720. |
| Service stuck in `activating`, restarts every ~2 min | It never signalled ready: the first frame never completed. Check the camera (`rpicam-hello --list-cameras`), the model path, and the journal. Also check the installed unit is the current one (`systemctl show ai-vision-drone -p Type` should be `notify`) and `NotifyAccess=main` is set. |
| Journal: `Camera stopped delivering frames ... exiting`, service restarts | The camera hung or failed. Occasional: fine, it recovered. Repeated: power (`vcgencmd get_throttled`), ribbon seating (power off first), thermal. |
| Journal: `Watchdog timeout`, then SIGABRT | The pipeline stopped completing frames for 10 s. Look at the lines just before it. |
| `Device or resource busy` from the IMX500 | Another process holds the camera: a leftover `tmux` run (`tmux ls`), the service, or a tool (`pgrep -af companion.main`). Only one at a time. |
| `ModuleNotFoundError: picamera2` though apt shows it installed | Wrong venv, or one made without `--system-site-packages`. Check `echo $VIRTUAL_ENV` and `grep include-system-site-packages "$VIRTUAL_ENV/pyvenv.cfg"`. Two venvs with the same name look identical in the prompt. |
| `ModuleNotFoundError` for pymavlink, websockets, cv2... | The venv is not active, or `pip install -e ".[video]"` was skipped after a pull. |
| `Multiple top-level packages discovered in a flat-layout` | Old checkout - `git pull`. |

## Flight controller link

| Symptom | Cause and fix |
|---|---|
| No heartbeat, zero bytes on `/dev/serial0` | **Baud mismatch** is the usual cause - try 57600 whatever the GCS shows. Check raw bytes: `cat /dev/serial0 \| od -An -tx1`. Then TX/RX crossing, GND, `raspi-config` serial, Bluetooth (`dtoverlay=disable-bt`). |
| "Link OK" but every telemetry field shows `--` | The FC is not streaming. The bridge requests streams on the first heartbeat and re-requests when position goes stale; check the journal for errors and that `SERIALx_PROTOCOL` is MAVLink2. |
| Journal: `MAVLink link lost (...) - reopening`, then `reopened` | Recovered on its own (FC reboot, unplug, wedged port). Frequent occurrences point at wiring, power or baud. |
| "Flight controller did not change mode" | A mode request was not confirmed after 3 sends. The FC may refuse the mode (BRAKE/LOITER need a position estimate), or the link is dropping messages. |
| "Arm rejected by flight controller" | Pre-arm checks failed - read the reason in Mission Planner's messages. |
| DISARM does nothing on the bench | ArduCopter thinks it is flying (land detector, props spinning). Use **Force disarm** (refused above 1.5 m). |
| Guidance never allowed, banner "RC override active" with hands off the sticks | A stick channel reads outside 1425-1575 µs. **Throttle counts too** - it must rest near centre. Check the app's RC inputs and the transmitter trims. |

## Detection and tracking

| Symptom | Cause and fix |
|---|---|
| No detection boxes for a clear subject | `journalctl` shows rate-limited `IMX500Detector` lines: "outputs is None" constantly = the network is not running (model path, firmware); "best score below score_threshold" = lower `camera.score_threshold`; "0 candidate detections" = the model genuinely sees nothing. Make sure you are on a recent commit (the `capture_request()` fix). |
| Boxes blink on and off | Should not happen on current code (frames without an AI result reuse the last result for 0.5 s). If the whole AI output stops for > 0.5 s, boxes clear - check the journal. |
| Blue-tinted video | Old checkout (fixed by requesting `RGB888`). |
| ~15 FPS instead of 30 | Old checkout (a redundant sleep halved the rate). |
| Target swaps to another person | Colour-based identity cannot separate similar clothing. It corrects when an alternative matches better, or holds. |
| Distance is wrong | Camera not calibrated (placeholder intrinsics); the target clipped by the frame edge (distance hidden on purpose); a crouching person (width fallback). |
| Follow will not move forward/back | Distance unknown (clipped box, class without a known size, taught object without a size) → vx held at 0 by design. |

## App and link

| Symptom | Cause and fix |
|---|---|
| Cannot reach the Pi from the phone | The phone must be on the Pi's Wi-Fi; check the IP (`hostname -I`) and port 8765 in Settings. |
| "Ground station link lost" while the app looks connected | The Pi heard nothing for 3 s: Wi-Fi trouble, the app frozen, or an old app build that does not ping. |
| Link drops repeatedly on weak Wi-Fi; journal "messages behind - disconnecting" | The phone could not keep up with updates; the Pi dropped it so it reconnects fresh. Move closer, or reduce interference. |
| Connected but black video | Old app build; current builds renegotiate video on every reconnect. |
| Recording not in the Gallery | Old app build; current builds save to `Movies/AI Vision Drone`. |

## Power and heat

| Symptom | Cause and fix |
|---|---|
| Pi freezes, only the red LED | Under-voltage. Use a 5 V / 5 A supply; `vcgencmd get_throttled` should be `0x0`. |
| Performance drops over time | Thermal throttling. Fit a heatsink and fan; watch the temperature. |

## Disk

Session logs self-prune to the newest 50. Video recordings (`~/ai-vision-drone-logs/recordings/`) are **never** deleted automatically - copy them off and clear them.
