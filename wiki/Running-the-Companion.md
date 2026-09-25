# Running the Companion

## Two modes

The mode comes from the `COMPANION_MODE` environment variable.

| Mode | Command | What runs |
|---|---|---|
| `sim` (default) | `python -m companion.main` | Synthetic camera and moving target, an embedded mock flight controller over loopback UDP, the real WebSocket server. Needs no hardware - run it on a laptop and point the app at it. |
| `hardware` | `COMPANION_MODE=hardware python -m companion.main` | Real AI Camera, real serial MAVLink (`/dev/serial0`), real video. Pi only. |

Other environment variables:

| Variable | Effect |
|---|---|
| `AI_VISION_DRONE_LATENCY_OVERLAY=1` | Burns a wall-clock timestamp into every video frame, for measuring glass-to-glass latency. Off by default. |

## Start-up sequence

1. Logging starts (`companion/logs/companion.log`, JSON, rotated at 10 MB, 5 backups).
2. **Startup health check** - every config file must parse, have its required keys, and have safety values in range. Every problem is listed at once, and nothing touches hardware until it passes.
3. Build the orchestrator (camera, detector, tracker, MAVLink, WebSocket, video).
4. Start the WebSocket server, open MAVLink, start the receive task.
5. Start the perception loop. After the first frame completes, the service tells systemd it is ready.

The orchestrator always starts in **IDLE**. A restart never resumes a guidance mode.

## The service

`deploy/ai-vision-drone.service`:

| Setting | Value | Meaning |
|---|---|---|
| `Type=notify` | | "Started" means the first frame has gone through the pipeline, not just that the process exists |
| `WatchdogSec=10` | | No watchdog ping for 10 s → systemd kills and restarts it |
| `TimeoutStartSec=120` | | Never ready (camera missing or dead at boot) → restart after 2 min |
| `Restart=always`, `RestartSec=2` | | Restarted whatever ended it |
| `StartLimitIntervalSec=0` | | systemd never gives up restarting |
| `TimeoutStopSec=10` | | A hung camera thread cannot hold up a restart |

The watchdog is pinged only while a frame has completed within `pipeline_max_frame_age_s` (5 s). A frozen event loop or a stalled perception loop stops the pings. A camera with no new frame for `camera.stall_timeout_s` (2 s) makes the process exit with **status 3**, and systemd restarts it. While the companion is down no setpoints arrive, and the FC holds position on its own `GUID_TIMEOUT`.

Everyday commands:

```bash
sudo systemctl status ai-vision-drone
sudo systemctl restart ai-vision-drone      # after a code or config change
sudo systemctl stop ai-vision-drone         # frees the camera for the tools
sudo systemctl disable ai-vision-drone      # stop auto-start on boot
journalctl -u ai-vision-drone -f            # live log
systemctl show ai-vision-drone -p NRestarts # how many restarts so far
```

## Where things are written

| What | Hardware mode | Sim mode |
|---|---|---|
| Application log | `~/ai-vision-drone/companion/logs/companion.log` (rotated) | `companion/logs/companion.log` |
| Session event log (JSONL, one per run, newest 50 kept) | `~/ai-vision-drone-logs/sessions/` | `companion/logs/sessions/` |
| Pi video recordings (never auto-deleted) | `~/ai-vision-drone-logs/recordings/` | - |
| Teach-mode photos | `companion/datasets/<name>/` (git-ignored) | same |

Clear old recordings by hand (copy them off first) before long recording sessions on a full card.

> The lab checklist's "handy commands" point at `companion/logs/sessions`, which is where sim mode writes. On the Pi in hardware mode, session logs are in `~/ai-vision-drone-logs/sessions/`.

### Session log events

Each line is one JSON event. The ones you will look for most:

| Event | Meaning |
|---|---|
| `mode_command` | The app changed mode or a parameter |
| `guidance_command` | One velocity setpoint actually reached the FC link |
| `abort`, `abort_hold_commanded`, `abort_hold_suppressed_rc_override` | STOP pressed; BRAKE sent (or not, under stick override) |
| `rc_override_loiter_requested` | Pilot stick input while in GUIDED → LOITER requested |
| `failsafe_rtl`, `failsafe_rtl_suppressed_rc_override` | Link loss or critical battery → RTL requested (or suppressed) |
| `mode_change_result` | Whether a requested flight mode was confirmed by the FC |
| `arm_command`, `arm_command_rejected`, `force_disarm_refused_airborne` | Arming activity |
| `auto_takeoff_sent`, `auto_takeoff_refused`, `auto_takeoff_timed_out` | Arm & Follow climb |
| `identity_swap_corrected`, `identity_lost`, `appearance_reacquired` | Identity check and re-lock |
| `obstacle_alert` | Something detected closer than 2 m |
| `target_recovery_found`, `target_recovery_rtl`, `target_recovery_land_confirmation_requested`, `land_confirmation_response` | Target-loss recovery |
| `grid_search_finished` | Sweep complete |
| `teach_started`, `teach_failed`, `teach_target_lost` | Teach mode |
| `record_start`, `record_stop` | Pi-side recording |

## Watching it live

Two windows from a laptop on the Pi's Wi-Fi:

```bash
ssh omkar@<pi-ip> journalctl -u ai-vision-drone -f           # the Pi's own log lines
python tools/live_monitor.py --uri ws://<pi-ip>:8765          # everything the Pi sends the app
```

`live_monitor.py` is read-only, so it can never mask a dead phone link. See [Tools](Tools#live_monitorpy).

## Running the tools on the Pi

The camera can only be opened by one process. Stop the service first, run the tool, then start the service again:

```bash
sudo systemctl stop ai-vision-drone
python tools/benchmark_detection.py --duration 30
sudo systemctl start ai-vision-drone
```
