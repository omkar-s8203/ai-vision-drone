# Configuration Reference

All configuration lives in `companion/config/*.yaml` and is tracked in git. After editing on the Pi, run `sudo systemctl restart ai-vision-drone`. The **startup health check** refuses to boot - listing every problem at once - if a required key is missing, a safety value is out of range, or the camera and calibration resolutions differ.

Keys marked **req** are required by the health check. Keys marked **not read** are documentation only - no code reads them today.

## safety_limits.yaml - cross-mode safety

| Key | Default | Allowed | Meaning |
|---|---|---|---|
| `min_obstacle_distance_m` **req** | 2.0 | | Any detected object closer than this stops guidance |
| `min_battery_pct` **req** | 20 | | At or below: guidance stops; RTL once if the Pi holds the aircraft in GUIDED |
| `min_takeoff_battery_pct` **req** | 30 | | Arm & Follow refuses to climb at or below |
| `min_gps_fix_type` **req** | 3 | | Minimum fix (3 = 3D) for Grid Search and takeoff |
| `max_hdop` | 2.5 | | HDOP above this counts as degraded GPS |
| `max_force_disarm_altitude_m` **req** | 1.5 | | Force disarm refused above this height |
| `detection_carry_max_s` **req** | 0.5 | 0.05-2.0 | Frames with no AI result reuse the last detections for at most this long |
| `target_hold_after_unseen_s` **req** | 0.3 | 0.05-1.0 | Follow/Orbit steer on the last box only while it is younger than this, then hold |
| `pipeline_max_frame_age_s` **req** | 5.0 | 1.0-9.0 | systemd watchdog is pinged only while a frame completed within this; must exceed `camera.stall_timeout_s` and stay under `WatchdogSec` (10) |

## hardware.yaml - devices

| Key | Default | Allowed | Meaning |
|---|---|---|---|
| `mavlink.connection` **req (hw)** | `/dev/serial0` | | FC serial device |
| `mavlink.baud` **req (hw)** | 57600 | | Must equal the FC's real TELEM baud |
| `mavlink.silence_reconnect_s` **req (hw)** | 5.0 | 2-60 | No MAVLink data this long → reopen the link |
| `mavlink.reconnect_max_delay_s` **req (hw)** | 5.0 | 0.5-30 | Longest wait between reopen attempts |
| `camera.width` / `height` / `target_fps` **req** | 1280 / 720 / 30 | | Stream format; must match the calibration |
| `camera.imx500_model_path` **req (hw)** | stock SSD MobileNetV2 `.rpk` | | On-sensor model |
| `camera.labels_path` | unset | | Class names file for a retrained model |
| `camera.bbox_order` | `yx` | `yx`, `xy` | Box order the model emits |
| `camera.score_threshold` | 0.35 | 0-1 | Minimum detection confidence |
| `camera.stall_timeout_s` **req (hw)** | 2.0 | 0.5-10 | No new frame this long → exit for a systemd restart |
| `rangefinder.enabled` / `port` / `baud` | false / `/dev/serial1` / 115200 | | TFmini-S |
| `tracker.impl` | `iou` | `iou`, `bytetrack` | Tracker implementation |
| `tracker.high_score_thresh` / `low_score_thresh` / `min_iou` | 0.6 / 0.1 / 0.3 | | ByteTrack only |
| `pi.power_source` | | | **not read** |

## network.yaml - operator link

| Key | Default | Meaning |
|---|---|---|
| `ws_host` **req** | `0.0.0.0` | WebSocket bind address |
| `ws_port` **req** | 8765 | WebSocket port |
| `comms_timeout_s` **req** | 3.0 | No message from the app this long → link lost, guidance stops |
| `comms_loss_rtl_s` **req** | 15.0 | Continuous loss this long while in GUIDED → RTL once |
| `ws_send_queue_max` **req** | 200 (10-10000) | Per-client backlog before a slow phone is disconnected |
| `mode`, `ssid`, `video_pipeline` | `ap`, `ai-vision-drone`, `aiortc` | **not read** - describe the setup |

## follow_limits.yaml - Follow

| Key | Default | Meaning |
|---|---|---|
| `max_speed_mps` | 3.0 | Speed ceiling (the app slider can go lower, never higher) |
| `min_speed_mps` | 0.5 | Lowest the slider can set |
| `max_accel_mps2` **req** | 1.5 | Acceleration limit on every axis |
| `max_reverse_speed_mps` | 1.0 | Backing away is slower (the camera cannot see behind) |
| `min_separation_m` / `max_separation_m` **req** | 3 / 15 | Bounds for the app's separation |
| `target_separation_m` **req** | 6.0 | Default separation |
| `target_altitude_m` | null | null = keep the target framed vertically; a number = hold that altitude |
| `min_altitude_m` / `max_altitude_m` **req** | 2 / 30 | Floor and ceiling |
| `lateral_deadband_px` / `vertical_deadband_px` | 20 / 20 | Centring deadbands |
| `pid.distance` / `lateral` / `vertical` / `altitude` | see file | Controller gains |

## orbit_limits.yaml - Orbit

Same speed, acceleration, deadband, altitude and PID keys as Follow, plus:

| Key | Default | Meaning |
|---|---|---|
| `orbit_radius_m` **req** | 8.0 | Default radius |
| `min_radius_m` / `max_radius_m` **req** | 3 / 20 | Bounds |
| `angular_speed_dps` | 15.0 | Speed around the circle |
| `direction` | 1 | 1 or -1 |

## grid_search_limits.yaml - Grid Search (all keys required except altitude)

| Key | Default | Meaning |
|---|---|---|
| `min_dimension_m` / `max_dimension_m` | 20 / 200 | Area bounds |
| `leg_spacing_m` | 15.0 | Distance between sweep legs |
| `search_speed_mps` / `max_speed_mps` | 2.5 / 2.5 | Cruise and ceiling |
| `waypoint_radius_m` | 3.0 | Arrival radius |
| `max_heading_error_deg_to_advance` | 25.0 | Only move forward when roughly facing the waypoint |
| `max_yaw_rate_rads` | 0.5 | Turn-rate limit |
| `search_altitude_m` | null | null = keep current altitude |
| `min_altitude_m` / `max_altitude_m` / `max_accel_mps2` | 2 / 30 / 1.5 | Limits |
| `pid.yaw` / `pid.altitude` | see file | Gains |

## auto_takeoff_limits.yaml - Arm & Follow

| Key | Default | Meaning |
|---|---|---|
| `altitude_m` | 10.0 | Climb height before following |
| `altitude_tolerance_m` | 1.0 | "Reached" window |
| `timeout_s` | 30.0 | Give up and return to idle |

## target_recovery.yaml - target-loss recovery

| Key | Default | Meaning |
|---|---|---|
| `search_timeout_s` | 60 | Search duration |
| `search_yaw_rate_rads` | 0.3 | Sweep turn rate |
| `sweep_half_period_s` | 4.0 | Reverse direction every this long |
| `low_battery_pct_threshold` | 20 | Below this, landing in place may be proposed |
| `assumed_return_speed_mps` | 5.0 | Placeholder for the "can it get home" estimate |
| `assumed_max_flight_time_s` | 900 | Placeholder |
| `rtl_safety_margin` | 1.5 | Multiplier on the return estimate |

## reidentification.yaml - identity and re-lock

| Key | Default | Meaning |
|---|---|---|
| `min_similarity` | 0.65 | Re-lock after loss needs at least this |
| `min_margin` | 0.08 | …and must beat the runner-up by this |
| `track_min_similarity` | 0.30 | Below this while tracking counts as a mismatch |
| `track_swap_frames` | 5 | Mismatch frames before switching to a better match |
| `track_drop_frames` | 20 | Mismatch frames before dropping the lock |
| `adapt_similarity` / `adapt_rate` | 0.80 / 0.10 | Only strong matches slowly update the remembered look |

## approach_limits.yaml - Approach-Test and RC override

| Key | Default | Meaning |
|---|---|---|
| `max_approach_speed_mps` | 1.0 | Approach speed |
| `min_boundary_m` | 2.0 | Stop distance |
| `rc_override_deadband` **req** | 0.15 | Stick deflection (fraction of half-travel from 1500 µs) counted as override, all four sticks including throttle |
| `geofence_radius_m`, `reacquire_timeout_s`, `comms_timeout_s` | 20 / 2.0 / 1.5 | **not read** (the live values are the FC fence, the 2 s code default, and `network.yaml`) |

## teach_limits.yaml - Teach mode

| Key | Default | Meaning |
|---|---|---|
| `dataset_root` **req** | `companion/datasets` | Where photos go |
| `sample_interval_s` **req** | 0.5 | Minimum time between photos |
| `min_center_shift_frac` / `min_scale_change_frac` / `min_repeat_s` | 0.03 / 0.08 / 3.0 | Skip near-duplicates |
| `max_samples_per_object` **req** / `max_total_mb` | 400 / 500 | Storage caps |
| `min_similarity` | 0.6 | Only save while the track still looks like the object |
| `jpeg_quality` | 90 | Photo quality |
| `custom_max_speed_mps` **req** | 1.5 | Follow/Orbit speed cap for taught objects |
| `min_box_px` **req** | 12 | Smallest box that can be taught |
| `max_area_change_factor` / `max_aspect_change_factor` | 1.8 / 1.8 | Tracker sanity limits |

## camera_calibration.yaml - intrinsics

`image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`. Currently **placeholders** (fx = fy = 900 at 1280x720). Write real values with `tools/calibrate_camera.py`. See [Distance Estimation](Distance-Estimation#calibration).

## Values in code, not config

| Value | Where |
|---|---|
| Subsystem watchdog timeout 2 s | `main.py` builders |
| Reacquire window 2 s | `CompanionOrchestrator(reacquire_timeout_s=2.0)` |
| Frame gap treated as a stall 0.5 s | `MAX_CONTROL_DT_S` in `main.py` |
| Position considered fresh 2 s | `POSITION_MAX_AGE_S` in `bridge.py` |
| Mode retry 1.5 s × 3 sends | `bridge.py` |
| First-frame allowance 15 s | `CAMERA_FIRST_FRAME_TIMEOUT_S` in `camera.py` |
| `WatchdogSec` 10 s, restart policy | `deploy/ai-vision-drone.service` |
