# Lab / Bench Test Checklist (props off) - gate before first flight

**Purpose.** Prove, on the bench with **propellers removed**, that the aircraft, flight
controller (FC), Pi, camera and Android app behave correctly and fail safely. Real flight
starts only after every **MANDATORY** item below passes.

**Scope.** This is the complete bench protocol for the code at commit `e2599f5` or later
(545 automated tests passing). It supersedes the bench parts of
`docs/flight-readiness-checklist.md` (its FLTMODE_CH steps are repeated here as Stage 4).
Why each mechanism exists: `docs/safety-case.md`. Message formats: `docs/protocol.md`.

---

## 0. Ground rules (read first)

1. **Propellers off for every stage in this document.** Physically remove them. Do not
   rely on "disarmed" or "props-off mode" - remove them. If a step would need the props
   on, it is a flight test, not a lab test, and is out of scope here.
2. **Stop on any FAIL.** Do not continue to the next stage. Write down what happened, fix
   or investigate, then **repeat the whole failed stage** (not just the failing line).
3. **Two people if possible**: one holds the transmitter (with a hand on the mode switch
   for the whole session), one runs the laptop/phone.
4. **The transmitter is the safety.** It must be on, bound, and the mode switch reachable at
   all times. The software backstops in this project sit on top of it, never instead of it.
5. **Record real values, not "OK".** Every check has a blank for the measured result.
   A checklist ticked without numbers proves nothing.
6. **Never leave a temporary test edit in place.** Some tests change a config value to force
   a condition (marked **TEMP EDIT**). Revert and restart the service straight afterwards
   (`git checkout <file>` on the Pi) and tick the revert box.
7. **MANDATORY** = blocks flight if it fails. **RECORD** = write the result down and tune
   later; not a blocker unless the result is clearly unsafe.

### Test record

| Field | Value |
|---|---|
| Date / location | |
| Tester(s) | |
| Git commit on laptop / on Pi (`git rev-parse --short HEAD`) | |
| Android app build (date installed) | |
| FC firmware + version (Mission Planner "Full Parameter" / Setup) | |
| Battery used (pack, cells, starting voltage / %) | |
| Weather / GPS sky view (indoor / outdoor) | |

### What you need

- Aircraft with **props removed**, fully charged pack, transmitter + receiver bound.
- Raspberry Pi 5 + AI Camera mounted as on the real aircraft, wired to the FC TELEM port.
- Laptop with Mission Planner (or QGroundControl) - USB to the FC for parameter work and
  live telemetry; SSH access to the Pi (`ssh omkar@<pi-ip>`).
- Android phone with the **current** app build installed and joined to the Pi's WiFi AP
  (`ai-vision-drone`).
- Tape measure (10 m+), a helper to act as the tracked "target", a second helper and two
  differently coloured shirts for the identity tests, a stopwatch.
- A clear outdoor spot with sky view for the GPS-dependent tests (Stage 5.3, Stage 8).
  Stages 1-4, 5 (except GPS), 6 and 7 can run indoors.

### Handy commands (on the Pi)

```bash
sudo systemctl status ai-vision-drone          # is it running?
sudo systemctl restart ai-vision-drone         # after any config edit
sudo systemctl stop ai-vision-drone            # frees the camera for the tools in Stage 6
journalctl -u ai-vision-drone -f               # live log (health check, errors, failsafes)
ls -t ~/ai-vision-drone/companion/logs/sessions | head -1        # newest session log
tail -f ~/ai-vision-drone/companion/logs/sessions/session_<ts>.jsonl   # live events
grep -c guidance_command ~/ai-vision-drone/companion/logs/sessions/session_<ts>.jsonl
```

Session-log events referenced below: `mode_command`, `guidance_command` (one per velocity
setpoint sent), `rc_override_loiter_requested`, `failsafe_rtl`, `failsafe_rtl_suppressed_rc_override`,
`auto_takeoff_sent` / `auto_takeoff_refused` / `auto_takeoff_timed_out`, `identity_lost`,
`identity_swap_corrected`, `obstacle_alert`, `arm_command_rejected`, `force_disarm_refused_airborne`,
`target_recovery_*`.

---

## Stage 1 - Software gate (laptop) - MANDATORY

| # | Check | Expected | Result |
|---|---|---|---|
| 1.1 | `.venv/Scripts/python -m pytest -q` on the commit you will run | `545 passed` (or more), 0 failed | |
| 1.2 | `cd android && gradle assembleDebug` | `BUILD SUCCESSFUL` | |
| 1.3 | Install that APK on the phone; note the install time | Installed | |
| 1.4 | Same commit is checked out on the Pi (`git pull`, `git rev-parse --short HEAD`) | Matches 1.1 | |
| 1.5 | `git status` on the Pi shows no uncommitted edits to `companion/config/*.yaml` | Clean (no leftover TEMP EDITs) | |

**Important:** the app **must** be the current build. The Pi now treats an app that sends
no periodic traffic as disconnected (Stage 9) - an old build would have guidance blocked.

---

## Stage 2 - Pi boot and self-check - MANDATORY

Props off, aircraft powered from the flight battery or a bench supply.

| # | Check | Expected | Result |
|---|---|---|---|
| 2.1 | Cold boot the Pi; time from power-on until `systemctl status ai-vision-drone` is `active (running)` | < 45 s | s |
| 2.2 | `journalctl -u ai-vision-drone -b` | No `StartupHealthCheckError`, no traceback; camera + MAVLink connect lines present | |
| 2.3 | **Health-check refusal works.** Stop the service; **TEMP EDIT** `companion/config/safety_limits.yaml`: delete the line `min_battery_pct: 20`; run `COMPANION_MODE=hardware python -m companion.main` | Exits immediately with `missing required key 'min_battery_pct'` - no hardware touched | |
| 2.4 | **Revert 2.3**: `git checkout companion/config/safety_limits.yaml`; `sudo systemctl start ai-vision-drone` | Service healthy again | ☐ reverted |
| 2.5 | Phone connects to the Pi (app **Link: CONNECTED**), video visible | Connected, live video | |
| 2.6 | Power-cycle the Pi 10 times (pull power, replug, wait for ready) | 10/10 come up healthy, **always in IDLE** (never resumes a guidance mode) | /10 |
| 2.7 | With the app connected: `journalctl` shows no repeating errors for 2 minutes | Quiet | |

---

## Stage 3 - Flight-controller configuration audit - MANDATORY

Every safety net in the software assumes these are set correctly. **I could not verify them
from code.** Connect Mission Planner over USB, read the *actual* values, write them down.
Values in "Required" are minimums for a safe first flight; adjust to your airframe but do
not leave any at "unknown".

| # | Parameter(s) | Required | Actual |
|---|---|---|---|
| 3.1 | `FLTMODE_CH` and `FLTMODE1..6` | One position = `GUIDED`; at least one = `LOITER` or `STABILIZE`; the channel is a real switch on your transmitter | |
| 3.2 | `BATT_MONITOR`, `BATT_CAPACITY`, `BATT_LOW_VOLT`/`BATT_LOW_MAH`, `BATT_CRT_VOLT`/`BATT_CRT_MAH`, `BATT_FS_LOW_ACT`, `BATT_FS_CRT_ACT` | Monitor enabled and reading correct voltage; low action = RTL, critical action = LAND (or RTL). **Battery % must show in the app** or the Pi's battery gates cannot work | |
| 3.3 | `FENCE_ENABLE`, `FENCE_TYPE`, `FENCE_RADIUS`, `FENCE_ALT_MAX`, `FENCE_ACTION` | Fence enabled with a radius/altitude appropriate to the test field; action = RTL (or Brake/Land) | |
| 3.4 | `GUID_TIMEOUT` (ArduCopter Guided velocity timeout) | Set and known (default 3 s). This is what stops the aircraft if the Pi dies | |
| 3.5 | `RTL_ALT`, `RTL_ALT_FINAL`, `LAND_SPEED` | `RTL_ALT` above the tallest obstacle at the flight site | |
| 3.6 | `FS_THR_ENABLE` (radio failsafe) and its action | Enabled, action RTL/Land | |
| 3.7 | `FS_EKF_ACTION`, `FS_EKF_THRESH`, GPS failsafe behaviour | Enabled, not "disabled" | |
| 3.8 | `ARMING_CHECK` | **Not** disabled (must stay "all checks") | |
| 3.9 | GPS: with sky view, `GPS fix type` and `HDOP` in Mission Planner | 3D fix (>=3), HDOP <= 2.5, satellites >= 8 | |
| 3.10 | Compass/heading: point the nose at a known direction; compare with a phone compass | Within ~15 deg; heading in app matches Mission Planner | |
| 3.11 | Accelerometer/compass calibrated, no pre-arm errors when armed on the bench | Arms cleanly | |

Save the full parameter file (`.param`) next to this record.

---

## Stage 4 - Hardware override (FLTMODE_CH) - MANDATORY

This is the actual safety guarantee (it works even if the Pi is dead). Test it **first with
the Pi off**, then with guidance active.

### 4A - Pi powered off

| # | Check | Expected | Result |
|---|---|---|---|
| 4A.1 | Power the FC with the **Pi off / disconnected** | | |
| 4A.2 | Cycle the transmitter mode switch through every position while watching Mission Planner's HUD | Reported flight mode matches `FLTMODE1..6` for every position | |

### 4B - Override while guidance is active

Pi running, FC connected, props off. FC armed (bench arming is fine with props removed).

| # | Check | Expected | Result |
|---|---|---|---|
| 4B.1 | Put the FC in `GUIDED` with the switch. In the app select a target (tap a person) and choose **Follow** | Guidance panel shows `GUIDANCE SENT` with changing vx/vy/vz/yaw values | |
| 4B.2 | Flip the transmitter switch away from `GUIDED` | FC mode changes immediately; app banner **"Flight controller not in AI guidance mode"**; panel goes to `GUIDANCE BLOCKED`; new `guidance_command` lines stop in the session log | |
| 4B.3 | Repeat 4B.1-4B.2 **20 times in a row** | **20/20.** Any miss = STOP, do not proceed | /20 |
| 4B.4 | Repeat 4B.3 with **Orbit** instead of Follow (10 times) | 10/10 | /10 |

### 4C - Stick override while in GUIDED (software backstop)

| # | Check | Expected | Result |
|---|---|---|---|
| 4C.1 | Follow engaged, FC in `GUIDED`. Deflect the roll stick beyond ~15% and hold | Banner **"RC override active - AI guidance paused"**; `guidance_command` stops; FC mode changes to **LOITER**; session log shows `rc_override_loiter_requested` **once** (not repeatedly) | |
| 4C.2 | Release the stick | Pi does **not** put the FC back into GUIDED by itself. The app shows a **Resume** button; the FC stays in LOITER until you act | |
| 4C.3 | Switch the FC back to `GUIDED` with the transmitter, tap **Resume** | Guidance resumes and ramps up from zero (no sudden jump in vx) | |
| 4C.4 | Put the FC in `STABILIZE` yourself, then deflect a stick | Pi does **not** touch the mode (no `rc_override_loiter_requested`) | |

### 4D - Operator STOP

| # | Check | Expected | Result |
|---|---|---|---|
| 4D.1 | Follow engaged, press **STOP/ABORT** in the app | Guidance stops within one frame; target forgotten; FC goes to **BRAKE** (needs GPS - note if FC refuses indoors); app mode returns to idle | |
| 4D.2 | Repeat while the pilot holds a stick deflected | Pi does **not** change the FC mode (pilot is flying) | |

---

## Stage 5 - Telemetry and coordinate correctness (Pi <-> FC) - MANDATORY

Goal: what the Pi and app believe about the aircraft equals what the FC knows. Compare the
app's Status tab against Mission Planner side by side.

| # | Check | Expected | Result |
|---|---|---|---|
| 5.1 | Flight mode, armed state | Identical in app and Mission Planner, updating within ~1 s | |
| 5.2 | Battery voltage / % | Within 0.2 V / 5 % of Mission Planner | |
| 5.3 | GPS: fix type, satellites, HDOP, lat/lon (outdoors) | Match; lat/lon within a few metres of Mission Planner | |
| 5.4 | Heading: rotate the aircraft slowly by hand through N, E, S, W | App heading tracks Mission Planner (0=N, 90=E clockwise) | |
| 5.5 | Attitude: tilt the nose up, then roll right | Pitch positive nose-up, roll positive right-side-down, matching Mission Planner | |
| 5.6 | Altitude: lift the aircraft ~2 m by hand and lower it | App altitude (above home) follows Mission Planner's; returns to ~0 | |
| 5.7 | RC inputs shown in the app | Match sticks/switch movement | |
| 5.8 | **Telemetry survives an FC reboot.** With the app showing altitude/GPS, reboot the FC (Mission Planner: "Reboot Autopilot", or briefly disconnect and reconnect FC power with the Pi kept powered) | Within ~10 s of the FC's heartbeat returning, altitude/GPS/battery values resume updating **without restarting the Pi service** | s |
| 5.9 | During 5.8 watch the app's health panel | `mavlink` shows the interruption, then recovers | |

If 5.8 fails, guidance would silently run on frozen altitude - do not proceed.

---

## Stage 6 - Camera, AI detection, tracking, distance

Stop the service first where a tool needs the camera (`sudo systemctl stop ai-vision-drone`),
restart it afterwards.

### 6A - Detection (RECORD, but a wildly bad result is a blocker)

| # | Check | Expected | Result |
|---|---|---|---|
| 6A.1 | `python tools/benchmark_detection.py --duration 30` | Detection rate >= 15 FPS, Pi CPU from detection < 15 %, CPU temp < 80 C | fps / % / C |
| 6A.2 | `python tools/detection_regression.py capture --duration 30 --out session.json`, then `python tools/detection_regression.py analyze session.json` with a person standing/walking in view | Consistent detections frame to frame; reacquire >= 90 %, false-lost <= 5 % | |
| 6A.3 | `python tools/ws_latency_benchmark.py --uri ws://<pi-ip>:8765 --count 100` from the laptop on the Pi WiFi | Round trip < 50 ms | ms |
| 6A.4 | Video: watch for lag walking in front of the camera | Glass-to-glass under ~200 ms, no freezing | |

### 6B - Camera calibration and distance (MANDATORY before trusting Follow)

The camera calibration in the repo is a **placeholder**. Follow's forward/back speed is
driven by the distance estimate, so this must be real.

| # | Check | Expected | Result |
|---|---|---|---|
| 6B.1 | Print a checkerboard (e.g. 9x6 inner corners), take 15-25 photos from varied angles at the **running resolution** (1280x720), then `python tools/calibrate_camera.py --images "calib_photos/*.jpg" --board-cols 9 --board-rows 6` | Writes `companion/config/camera_calibration.yaml` with fitted fx/fy/cx/cy; `image_width/height` = 1280/720 (the boot check refuses a mismatch) | |
| 6B.2 | Restart the service; select a helper (standing upright) as the target | Tracking box locks | |
| 6B.3 | Helper stands at **3 m, 5 m, 8 m, 12 m** (tape-measured), facing the camera, full body in frame, not touching the frame edge. Read the distance shown next to the tracked target (AI Modes tab) | Within **15 %** of the tape at 3-15 m: 3 m -> 2.55-3.45, 5 m -> 4.25-5.75, 8 m -> 6.8-9.2, 12 m -> 10.2-13.8 | m / m / m / m |
| 6B.4 | Repeat 6B.3 with the helper turned side-on | Distance changes by no more than a few % (Follow uses body **height**, not width) | |
| 6B.5 | Move the helper so their feet/head touch the frame edge | **No distance is shown** (unknown) rather than a wrong number; Follow would hold forward speed at 0 | |
| 6B.6 | Helper crouches / sits | Estimate degrades (fallback to width) - note by how much | RECORD |

### 6C - Tracking, identity, target loss

| # | Check | Expected | Result |
|---|---|---|---|
| 6C.1 | Tap a person; overlay box + "target locked" alert | Locks in <1 s | |
| 6C.2 | Person walks steadily across the frame for 60 s | Lock never lost, box smooth (not jittering) | |
| 6C.3 | Two people in **clearly different colours** (red vs blue shirt) cross paths 10 times; target = red | Lock stays on red in >= 9/10 crossings; if it swaps, it corrects itself within ~1 s (`identity_swap_corrected` in the log) | /10 |
| 6C.4 | Same as 6C.3 but the red target leaves the frame while the stranger stays. **Engage Follow first** (props off, FC in GUIDED) - the hold banners only appear while Follow/Orbit is engaged; otherwise check for `identity_lost` in the session log | Lock does **not** silently follow the stranger for long: within about 1 s the banner **"Not sure this is your target - holding position"** appears and commands go to 0, then target lost | |
| 6C.5 | Two people in **similar clothing** cross paths | RECORD what happens (swap / hold / correct). Colour histograms cannot separate similar clothing - this defines a real limit for flight | RECORD |
| 6C.6 | Target steps behind an obstacle for <1 s and returns | Re-locked, no target-lost alert (>= 90 % of trials) | /10 |
| 6C.7 | Target leaves the frame for >2 s | "Target lost" alert; if Follow was engaged, search behaviour starts (Stage 7) | |
| 6C.8 | Target returns after being lost (same person, same clothing) | Auto re-locked by appearance ("AI learning") without a tap | |
| 6C.9 | **Obstacle proximity**: a person walks to ~1.5 m from the camera | Banner **"Obstacle too close: person at ..."** and all guidance stops (`obstacle_alert` in log) | |

### 6D - Teach mode (RECORD; MANDATORY only if you will fly with taught objects)

See `docs/teach-and-train.md`. Props off. Use an object the AI does not know (a coloured box, a bag).

| # | Check | Expected | Result |
|---|---|---|---|
| 6D.1 | **TEACH NEW OBJECT**, draw a tight box, name it, give real width/height | Chip shows `TEACHING: <name> (n)`; message "Learning ..."; Track/Follow/Orbit sheet opens | |
| 6D.2 | Walk the object around slowly for 60 s | Lock holds; photo count `n` rises steadily (roughly 1 per second while moving) | n = |
| 6D.3 | Look at the CPU/fps in the health panel while teaching | fps stays >= 15; no link or heartbeat problems (the tracker runs off the control loop) | fps / CPU |
| 6D.4 | Check the tracked box against the object at 3 m, 6 m, 10 m | Box stays on the object; distance within 15 % of the tape | |
| 6D.5 | Cover the object / take it out of view > 2 s | Tracking drops (target lost), chip clears, **does not** re-lock on its own | |
| 6D.6 | Move the camera so a similar-looking background fills the box | Drift is caught: "Not sure this is your target - holding position" (Follow engaged) or target lost | |
| 6D.7 | Follow the taught object (props off, GUIDED) | Commanded speeds never exceed **1.5 m/s**; with no real size entered, vx stays 0 | |
| 6D.8 | Tap a detected person / press STOP | Teaching ends, normal tracking resumes / everything stops | |
| 6D.9 | Inspect `companion/datasets/<name>/`: open 10 random photos with their `labels/*.txt` boxes drawn | Box sits on the object in every one; no photos with the object cut off at the edge | |
| 6D.10 | Teach with a hostile name (`../../evil`) | Stored as `evil` inside `companion/datasets/` - nothing outside that folder | |


---

## Stage 7 - Guidance dry-run (props off, armed, GUIDED) - MANDATORY

First time real velocity commands go to the real FC. Watch the app's **guidance panel**
(vx, vy, vz, yaw rate). Convention: vx +forward, vy +right, vz +**down** (negative = climb),
yaw rate + = clockwise (turn right). Limits: max speed 3.0 m/s, acceleration 1.5 m/s^2,
**reverse (backing away) max 1.0 m/s**, separation 3-15 m (default 6), altitude 2-30 m.

Set the FC to `GUIDED` with the switch and arm. Keep your hand on the mode switch.

### 7A - Follow

| # | Check | Expected | Result |
|---|---|---|---|
| 7A.1 | Target centred, at ~the separation (6 m) | vx ~ 0, yaw ~ 0 (deadband +-20 px) | |
| 7A.2 | Target moves to the **right** of the frame | yaw rate **positive** | |
| 7A.3 | Target moves to the **left** | yaw rate **negative** | |
| 7A.4 | Target stands **far** (~12 m) | vx **positive**, and it **ramps**: from 0 to ~3 m/s takes >= ~2 s (never a step) | s |
| 7A.5 | Target close (~3 m) | vx **negative** and **never beyond -1.0** | |
| 7A.6 | Aircraft on the bench (altitude < 2 m), altitude slider default 10 m | vz **<= 0** (climb command or zero); **never positive** while at/below 2 m | |
| 7A.7 | Set the altitude slider to its minimum (2 m) | vz stays **0** or negative - **no descent command at/below 2 m** | |
| 7A.8 | Hide the target for <2 s (cover the lens / step out) | Commands go to **exactly 0** (hold), banner **"Target not visible - holding position"**; when the target returns, vx **ramps up from 0** | |
| 7A.9 | Guidance panel **Speed slider** set to 1.0 while commanding a large vx | vx never exceeds 1.0 (takes effect immediately) | |
| 7A.10 | Send an out-of-range value: in the app set separation to 3 and to 15 (limits) | Pi applies within 3-15 (clamped). (Out-of-range values from anything else are clamped on the Pi - covered by automated tests) | |

### 7B - Orbit

| # | Check | Expected | Result |
|---|---|---|---|
| 7B.1 | Orbit engaged, target centred | vy **positive** (strafe right), magnitude ~ 0.26 rad/s x distance, ramping; vx holds the radius (default 8 m) | |
| 7B.2 | Backing-away component | vx never below -1.0 | |
| 7B.3 | Same altitude-floor checks as 7A.6/7A.7 | vz never positive at/below 2 m | |

### 7C - Vertical and stability behaviour

| # | Check | Expected | Result |
|---|---|---|---|
| 7C.1 | Watch the commands for 5 minutes of normal target motion | No oscillation/hunting around the separation; vx settles | |
| 7C.2 | Stall test: pause the companion for ~2 s (`sudo kill -STOP <pid>` then `sudo kill -CONT <pid>`; pid from `systemctl status`) | **No** setpoints are sent during the stall (the FC's `GUID_TIMEOUT` holds); after resuming, the first commands **ramp from 0** - no step to the old speed | |
| 7C.3 | Camera loss: unplug the camera (or cover-and-stall it) for ~2 s while Follow is active | Guidance stops (`System check failed - guidance paused`); after recovery it restarts from 0. Reseat the camera with the Pi **powered off** if it did not recover | |
| 7C.4 | Altitude-stream loss is covered by **5.8** (FC reboot): confirm the vertical command was 0 while altitude was unknown and resumed after the stream returned | | |

### 7D - Target-loss recovery

| # | Check | Expected | Result |
|---|---|---|---|
| 7D.1 | Follow engaged, target out of view for >2 s | Panel **"SEARCHING FOR TARGET"**, yaw-only command (vx/vy/vz = 0) | |
| 7D.2 | Target returns during the search | Search cancels, Follow resumes (ramping from 0) | |
| 7D.3 | **TEMP EDIT** `companion/config/target_recovery.yaml`: `search_timeout_s: 10`; restart. Keep the target out of view | After ~10 s the Pi requests **RTL** (healthy battery) - FC mode changes to RTL | |
| 7D.4 | **Revert 7D.3** (`git checkout companion/config/target_recovery.yaml`), restart | | ☐ reverted |
| 7D.5 | RTL suppressed if the pilot holds a stick during 7D.3 | No mode change (`target_recovery_rtl_suppressed_rc_override` in log) | |

---

## Stage 8 - Arm & Follow, GPS-dependent behaviour, battery, force-disarm

Do the GPS items **outdoors with sky view** (fix >= 3D, HDOP <= 2.5). Props off.

### 8A - Arm & Follow (auto-takeoff sequence)

| # | Check | Expected | Result |
|---|---|---|---|
| 8A.1 | Tap a target, choose **Arm & Follow**, confirm the "motors will become live" dialog | FC arms, goes to GUIDED. Banner **"Climbing to safe altitude - following starts when reached"**. `auto_takeoff_sent` appears in the log **once**. **No velocity commands** (`guidance_command`) are sent while climbing | |
| 8A.2 | Props are off, so altitude never rises. Wait. **Caution:** the FC keeps executing its takeoff and may spool the motors up hard with no props - keep clear, and **disarm** right after this check | After **30 s**: `auto_takeoff_timed_out` in the log, mode falls back to idle, **Follow never starts** | s |
| 8A.3 | Voice/alert: "Following target" must **not** be announced during the climb | Not spoken | |
| 8A.4 | **TEMP EDIT** `companion/config/safety_limits.yaml`: `min_takeoff_battery_pct: 100`; restart; repeat 8A.1 | Banner **"Takeoff refused - battery too low"**; **no** takeoff command sent; mode idle | |
| 8A.5 | **Revert 8A.4** (`git checkout companion/config/safety_limits.yaml`), restart | | ☐ reverted |
| 8A.6 | Bad GPS (indoors / antenna covered so fix < 3D): try Arm & Follow | Either the FC rejects the arm ("Arm rejected" alert) or the banner **"Takeoff refused - no good GPS fix"** - in both cases **no takeoff command** is sent | |

### 8B - Grid search (needs a good GPS fix)

| # | Check | Expected | Result |
|---|---|---|---|
| 8B.1 | Aircraft facing north, FC in GUIDED. Start grid search 40 m x 40 m | Route appears on the live map; starts from the current position | |
| 8B.2 | First leg runs east (90 deg right of the heading). Aircraft still facing north | yaw rate **positive**, vx = 0 (not facing the waypoint yet) | |
| 8B.3 | Slowly rotate the aircraft **clockwise** by hand toward east | yaw rate falls toward 0; when within ~25 deg, vx starts and **ramps** (max 2.5 m/s) | |
| 8B.4 | Rotate the aircraft **counter-clockwise** past north | yaw rate stays positive/large (sign is correct for the shorter turn) | |
| 8B.5 | Start with a bad fix (cover the GPS antenna until fix < 3D) | Grid search **refuses to start** (mode returns to idle) | |
| 8B.6 | Start with a good fix, then cover the antenna mid-sweep | Commands stop; banner **"GPS fix degraded - holding position"**; recovers/holds when fix returns | |
| 8B.7 | Start with width/height at the slider extremes (20, 200) | Plans a sane route (no freeze, map responsive). (Out-of-range values are clamped on the Pi - covered by tests) | |

### 8C - Battery and geofence failsafes

| # | Check | Expected | Result |
|---|---|---|---|
| 8C.1 | **Precondition:** battery % is visible in the app (Stage 3.2). If it is not, skip 8C.2-8C.4 and treat battery protection as **FC-only** | | |
| 8C.2 | **TEMP EDIT** `companion/config/safety_limits.yaml`: `min_battery_pct: 100`; restart. FC armed in GUIDED, Follow engaged | Banner **"Battery critically low - guidance stopped"**; guidance stops; Pi requests **RTL once** (`failsafe_rtl`, reason `battery_critical`) | |
| 8C.3 | Switch the FC back to GUIDED yourself | Pi does **not** re-request RTL (latch) | |
| 8C.4 | **Revert 8C.2** (`git checkout companion/config/safety_limits.yaml`), restart | | ☐ reverted |
| 8C.5 | Geofence: set a small fence (e.g. `FENCE_RADIUS` 5 m) in Mission Planner; carry the armed aircraft (props off) beyond it | Fence breach shown; guidance stops with banner **"Geofence breached - guidance stopped"**; FC's own fence action fires per `FENCE_ACTION`. **Restore the real fence afterwards** | ☐ restored |

### 8D - Force disarm safety

| # | Check | Expected | Result |
|---|---|---|---|
| 8D.1 | Armed, aircraft on the ground: **Disarm** | Disarms (or FC refuses - note which) | |
| 8D.2 | Armed; lift the aircraft by hand to **> 2 m** above start; press **Force disarm** and confirm | **Refused**: alert "Disarm rejected by flight controller", stays armed, `force_disarm_refused_airborne` in the log | |
| 8D.3 | Lower to the ground, **Force disarm** | Disarms | |
| 8D.4 | A normal (unforced) disarm at 2 m | Sent to the FC (the FC decides - ArduCopter normally refuses in flight) | |

---

## Stage 9 - Operator-link (phone) failsafe - MANDATORY

This was a real defect: loss of the phone link used to take tens of seconds to notice.
Now: the app pings every 500 ms; **no message for 3 s = link lost**; **15 s more = RTL**.

Setup: FC armed in **GUIDED**, Follow engaged with a tracked target, **guidance panel showing
`GUIDANCE SENT`**, Pi session log tailing (`grep guidance_command`).

| # | Check | Expected | Result |
|---|---|---|---|
| 9.1 | Turn the phone's WiFi off (airplane mode) at time T | `guidance_command` lines **stop within ~4 s** of T (link declared lost after 3 s) | s |
| 9.2 | Keep it off | At about **T + 18 s** (3 s detection + 15 s) the FC mode changes to **RTL**; journal shows `Failsafe RTL requested (comms_loss)`; session log `failsafe_rtl` | s |
| 9.3 | Keep it off for another minute | **Only one** RTL request (no repeats) | |
| 9.4 | Restore WiFi, reconnect the app (after the RTL in 9.2) | App reconnects; the Pi is idle (RTL cleared the requested mode) and does **not** resume Follow | |
| 9.5 | **Brief dropout:** WiFi off for 5-8 s, then on | Guidance pauses (link chip shows the drop), **no RTL** (< 15 s). Once the link returns, Follow **resumes by itself** (ramping from 0) if the target is still tracked and the FC is still in GUIDED - this is the current design; decide if you accept it | |
| 9.6 | **Half-dead link:** with the app open, walk out of WiFi range with the phone (or block the antenna) | Same as 9.1-9.2 - the app also shows the link as lost within a few seconds | |
| 9.7 | Repeat 9.1-9.2 with the pilot **holding a stick** (RC override) | Pi does **not** change the mode (`failsafe_rtl_suppressed_rc_override`) | |
| 9.8 | Repeat 9.1-9.2 with the FC in **LOITER** (not GUIDED) | Pi does **not** change the mode | |
| 9.9 | Pi-side kill: while Follow is engaged, `sudo systemctl stop ai-vision-drone` | Setpoints stop instantly; the FC (per `GUID_TIMEOUT`) holds - confirm in Mission Planner that it stops commanding motion; nothing restarts guidance on its own | |

---

## Stage 10 - Soak, thermals, boot behaviour

| # | Check | Expected | Result |
|---|---|---|---|
| 10.1 | Run the full stack 30 minutes (camera + AI + tracking + video + MAVLink + recording) | No crash/restart (`systemctl status` uptime unbroken), no watchdog `stale_subsystems` banners | min |
| 10.2 | During 10.1 watch Pi CPU temperature | < 80 C, no throttling (`vcgencmd get_throttled` = `0x0`) | C |
| 10.3 | During 10.1 watch fps/latency in the health panel | fps >= 15, no growth in latency over time | |
| 10.4 | Brown-out check: run a motor-power event with **props off** (throttle blip while armed) while the Pi runs | Pi does not reboot, camera and MAVLink stay alive | |
| 10.5 | Kill the service mid-session (`kill -9`) | systemd restarts it within ~3 s, **in IDLE** | |
| 10.6 | Record/stop recording several times; check the file plays | Recording works, video stays smooth while recording | |

---

## Stage 11 - Simulation (optional but recommended)

Real ArduPilot SITL needs Linux/WSL2. If available (`sim/sitl_harness.py`), run the
guidance modes against it, including a mid-run RC-override/mode-switch and a fence breach,
to see the FC's own behaviour without risking the aircraft. Not a blocker if unavailable;
note "not run".

---

## Exit criteria - go / no-go for first flight

**All must be true:**

- [ ] Stage 1: software gate passed on the exact commit running on the Pi.
- [ ] Stage 2: boots healthy 10/10, always idle.
- [ ] Stage 3: **every** FC parameter recorded with a real value; battery % visible; fence, radio and battery failsafes configured.
- [ ] Stage 4: hardware override **20/20** (Follow) and 10/10 (Orbit); stick override -> LOITER works; STOP works.
- [ ] Stage 5: telemetry matches Mission Planner; **FC-reboot recovery (5.8) passed**.
- [ ] Stage 6B: camera **really calibrated**; distance within 15 % at 3-12 m.
- [ ] Stage 7: every commanded-velocity **sign** correct; ramps (no steps); reverse <= 1.0; **no descent at/below 2 m**; holds when target unseen.
- [ ] Stage 8: takeoff refusals, force-disarm guard, GPS gating behave as expected; no TEMP EDIT left in place.
- [ ] Stage 9: link loss stops guidance in <= ~4 s and RTL fires once at ~18 s; suppressed under RC override.
- [ ] Stage 10: 30-min soak clean, temps OK.
- [ ] `git status` on the Pi is clean (no leftover config edits); `git rev-parse` recorded.

**Any unchecked mandatory item = NO-GO.** Fix, then repeat that whole stage.

### Known limits you are accepting for first flight (be explicit)

1. **Obstacle detection is vision-only and class-based** (people, cars, ...). It does not see walls, trees, poles, wires or glass. Fly **only in a large, open, obstacle-free area**, well clear of anything a camera could miss.
2. **Identity matching is colour-based.** Similar clothing can confuse it (Stage 6C.5 result).
3. **A dead Pi or camera stops setpoints; the FC then holds position (GUID_TIMEOUT) - it does not land.** The pilot must take over with the switch.
4. **Return-to-launch flies a straight line at `RTL_ALT`** - confirm the path is clear.
5. **No SITL / flight test** of these behaviours existed before this bench series (unless Stage 11 was run).

### After the lab: first-flight staging (do not skip ahead)

Follow the plan's M14 stages, each with its own go/no-go, an experienced pilot on the
switch, an open field, low wind, full battery, and a spotter:

1. **Tethered/low hover, Normal RC mode, Pi passive** (video + telemetry only, no guidance) - check vibration, video and telemetry under real motors and RF.
2. **Free hover in LOITER**, AI tracking active but **not** driving the aircraft.
3. **Follow at low speed** (`follow_max_speed_mps` slider ~1.0, separation >= 8 m), pilot's finger on the switch, first with a slow-walking helper.
4. Only after several clean sessions: larger speeds, Orbit, Arm & Follow auto-takeoff.
5. **Approach-Test: not until a separate go/no-go review.**

**Pre-flight quick check (every flying day):** props secure and correct direction; battery
level and voltage; transmitter mode switch tested; GPS 3D fix, HDOP <= 2.5; fence set;
`RTL_ALT` right for the site; phone connected (Link OK, battery % visible); no TEMP EDITs
(`git status` clean); STOP button tested; wind/weather acceptable; area clear.

---

## Appendix A - Quick reference: what you should see

| App banner / alert | Meaning | Typical cause |
|---|---|---|
| Flight controller not in AI guidance mode | FC is not in GUIDED | Switch not on GUIDED, or pilot override |
| RC override active - AI guidance paused | Stick deflection detected | Pilot input (FC goes to LOITER) |
| Ground station link lost - guidance paused | Pi heard nothing from the app for 3 s | WiFi drop, app frozen, old app build |
| Target lost - guidance paused | Tracker lost the target | Target left view / occluded |
| Obstacle too close: `<class>` at `<m>` | Any detected object under 2 m | Person/vehicle too near the camera |
| Geofence breached - guidance stopped | FC reports a fence breach | Outside fence radius/altitude |
| Battery critically low - guidance stopped | Battery <= `min_battery_pct` (20 %) | Low pack |
| System check failed - guidance paused | A subsystem heartbeat went stale | Camera, tracker, MAVLink or RC telemetry stopped |
| Climbing to safe altitude - following starts when reached | Auto-takeoff climb in progress | Arm & Follow |
| Target not visible - holding position | Brief target loss; zero-velocity hold | Occlusion, target out of frame |
| Not sure this is your target - holding position | Appearance no longer matches | Possible target swap |
| GPS fix degraded - holding position | Grid search has no good/fresh fix | Poor sky view, antenna fault |
| Takeoff refused - no good GPS fix / battery too low | Arm & Follow pre-checks failed | Bad fix, pack under 30 % |

## Appendix B - Key limits (from the config files)

| Setting | Value | File |
|---|---|---|
| Follow max speed / accel / reverse | 3.0 m/s / 1.5 m/s^2 / 1.0 m/s | `follow_limits.yaml` |
| Follow separation range / default | 3-15 m / 6 m | `follow_limits.yaml` |
| Altitude floor / ceiling (Follow, Orbit, Grid) | 2 m / 30 m | `follow_limits.yaml`, `orbit_limits.yaml`, `grid_search_limits.yaml` |
| Orbit radius range / default / angular speed | 3-20 m / 8 m / 15 deg/s | `orbit_limits.yaml` |
| Grid search speed / area size | 2.5 m/s / 20-200 m | `grid_search_limits.yaml` |
| Auto-takeoff altitude / tolerance / timeout | 10 m / 1 m / 30 s | `auto_takeoff_limits.yaml` |
| Obstacle minimum distance | 2.0 m | `safety_limits.yaml` |
| Critical battery / takeoff battery | 20 % / 30 % | `safety_limits.yaml` |
| GPS: min fix type / max HDOP | 3 (3D) / 2.5 | `safety_limits.yaml` |
| Force-disarm refused above | 1.5 m | `safety_limits.yaml` |
| Link timeout / RTL after continuous loss | 3 s / 15 s | `network.yaml` |
| Target reacquire window / search timeout | 2 s / 60 s | code default / `target_recovery.yaml` |
| Identity: swap after / drop after (frames) | 5 / 20 | `reidentification.yaml` |
| Telemetry treated as stale after | 2 s | `mavlink/bridge.py` |

## Appendix C - Results summary

| Stage | Result (PASS / FAIL / N-A) | Date | Notes / evidence (photo, log, param file) |
|---|---|---|---|
| 1 Software gate | | | |
| 2 Pi boot / self-check | | | |
| 3 FC configuration | | | |
| 4 Hardware override | | | |
| 5 Telemetry correctness | | | |
| 6 Camera / AI / tracking / distance | | | |
| 7 Guidance dry-run | | | |
| 8 Arm & Follow / GPS / battery / force-disarm | | | |
| 9 Operator-link failsafe | | | |
| 10 Soak / thermals | | | |
| 11 Simulation (optional) | | | |
| **Go / No-go** | | | Signed: |
