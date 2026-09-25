# Lab Testing and Flight Readiness

The complete props-off bench protocol is `docs/lab-test-checklist.md` in the repo. Print it and fill in real values. This page summarises what it covers and the order to follow. (`docs/flight-readiness-checklist.md` is the older two-step version; its steps reappear as Stages 4 and 7.)

## Ground rules

1. **Propellers off - physically removed - for every stage.** If a step needs props, it is a flight test, not a lab test.
2. **Stop on any FAIL.** Investigate, fix, then repeat the whole stage.
3. **Two people**: one on the transmitter with a hand on the mode switch the whole session, one on the laptop/phone.
4. **The transmitter is the safety.** It is on, bound and reachable at all times.
5. **Record real numbers**, not "OK".
6. **Never leave a TEMP EDIT in place.** Some tests change a config value to force a condition; revert with `git checkout <file>` and restart straight away.
7. **MANDATORY** blocks flight if it fails; **RECORD** is tuned later.

## Stages

| Stage | What it proves | Key checks |
|---|---|---|
| **1 Software gate** (MANDATORY) | The exact commit is healthy | Full test suite passes (763+ today); Android build succeeds; the same commit is on the Pi with no stray config edits |
| **2 Pi boot** (MANDATORY) | Clean, repeatable start-up | Ready in < 45 s; the health check refuses a broken config; 10/10 power cycles come up healthy and **always in IDLE** |
| **3 FC configuration** (MANDATORY) | The FC's own failsafes are real | `FLTMODE_CH`/`FLTMODE1-6`, battery monitor and failsafes, fence, `GUID_TIMEOUT`, `RTL_ALT`, radio and EKF failsafes, `ARMING_CHECK` on, GPS 3D fix with HDOP ≤ 2.5, compass, arms cleanly |
| **4 Hardware override** (MANDATORY) | The pilot always wins | Switch works with the **Pi off**; flipping out of GUIDED during Follow stops guidance **20/20** (Orbit 10/10); stick override → LOITER, no automatic return to GUIDED; STOP → BRAKE; nothing changes the mode while the pilot holds a stick |
| **5 Telemetry** (MANDATORY) | The Pi sees what the FC sees | Mode, battery, GPS, heading, attitude signs, altitude, RC inputs match Mission Planner; **telemetry recovers after an FC reboot** without restarting the service |
| **6 Camera, AI, tracking, distance** | Perception is trustworthy | Detection ≥ 15 FPS; stable boxes (no blinking); WS round trip < 50 ms; **real calibration** and distance within 15 % at 3-12 m (MANDATORY); identity across crossings; quick re-lock; obstacle banner at ~1.5 m; Teach mode if you will use it |
| **7 Guidance dry run** (MANDATORY, armed, GUIDED, props off) | Commands are correct | Yaw sign follows the target; vx ramps (never steps) and never below -1.0; **no descent at or below 2 m**; speed slider caps immediately; brief misses do not stutter; longer ones hold; stall, camera-loss and hang tests recover into IDLE; recovery search, then RTL |
| **8 Arm & Follow, GPS, battery, force-disarm** | Takeoff and GPS gating | Climb before follow; no "Following" announcement during the climb; takeoff refused on low battery or bad GPS; Grid Search yaw/advance behaviour, refuses on a bad fix, holds when GPS degrades; battery and fence stop guidance; force-disarm refused above 1.5 m |
| **9 Operator link** (MANDATORY) | Losing the phone is safe | Guidance stops within ~4 s of Wi-Fi off; RTL once at ~18 s; no RTL under stick override or outside GUIDED; brief dropouts resume; `systemctl stop` stops setpoints; lost mode requests are retried; a slow phone never freezes the Pi |
| **10 Soak and boot** | Endurance | 30 min full stack with no restarts or stale banners; CPU < 80 °C, not throttled; `kill -9` → back in ~3 s in IDLE; recording works; the unit shows `Type=notify`, `WatchdogUSec=10s`, and `NRestarts` does not grow |
| **11 SITL** (optional) | FC behaviour without risk | Guidance, mode switches and fence breach against real ArduPilot SITL if available |

## Go / no-go for first flight

**All** must be true:

- [ ] Stage 1 passed on the exact commit running on the Pi.
- [ ] Stage 2: boots healthy 10/10, always idle.
- [ ] Stage 3: every FC parameter recorded; battery % visible; fence, radio and battery failsafes configured.
- [ ] Stage 4: hardware override 20/20 (Follow) and 10/10 (Orbit); stick override → LOITER; STOP works.
- [ ] Stage 5: telemetry matches; FC-reboot recovery passed.
- [ ] Stage 6B: camera really calibrated; distance within 15 % at 3-12 m.
- [ ] Stage 7: every velocity sign correct; ramps; reverse ≤ 1.0; no descent at/below 2 m; holds when the target is unseen.
- [ ] Stage 8: refusals, force-disarm guard and GPS gating as expected; no TEMP EDIT left.
- [ ] Stage 9: link loss stops guidance ≤ ~4 s; RTL fires once at ~18 s; suppressed under stick override.
- [ ] Stage 10: 30-minute soak clean, temperatures OK.
- [ ] `git status` on the Pi is clean; commit recorded.

Any unchecked mandatory item is **NO-GO**.

## After the lab: flight stages (do not skip ahead)

Each stage has its own go/no-go, an experienced pilot on the switch, an open field, low wind, a full battery and a spotter:

1. **Tethered/low hover in Normal RC, Pi passive** (video and telemetry only).
2. **Free hover in LOITER**, AI tracking active but not driving the aircraft.
3. **Follow at low speed** (speed slider ~1.0 m/s, separation ≥ 8 m), a slowly walking helper, finger on the switch.
4. Only after several clean sessions: higher speeds, Orbit, Arm & Follow.
5. **Approach-Test: not until a separate go/no-go review.**

## Every flying day

Props secure and the right way round · battery voltage · transmitter mode switch tested · GPS 3D fix, HDOP ≤ 2.5 · fence set · `RTL_ALT` right for the site · phone connected, battery % visible · `git status` clean on the Pi · STOP tested · weather acceptable · area clear.

## Banner quick reference

| Banner | Meaning | Typical cause |
|---|---|---|
| Flight controller not in AI guidance mode | FC not in GUIDED | Switch not on GUIDED, or pilot override |
| RC override active - AI guidance paused | Stick deflection | Pilot input (FC goes to LOITER) |
| Ground station link lost - guidance paused | Nothing from the app for 3 s | Wi-Fi drop, app frozen, old app build |
| Target lost - guidance paused | Tracker lost the target | Out of view or occluded |
| Obstacle too close: `<class>` at `<m>` | A detected object under 2 m | Person or vehicle near the camera |
| Geofence breached - guidance stopped | FC reports a breach | Outside the fence |
| Battery critically low - guidance stopped | Battery ≤ 20 % | Low pack |
| System check failed - guidance paused | A subsystem went stale | Camera, tracker, MAVLink, link or RC telemetry stopped |
| Target not visible - holding position | Unseen ≥ 0.3 s | Occlusion |
| Not sure this is your target - holding position | Identity check failed | Someone similar crossed |
| Climbing to safe altitude | Arm & Follow climb | Normal |
| GPS fix degraded - holding position | Grid Search without a good fix | Poor sky view |
