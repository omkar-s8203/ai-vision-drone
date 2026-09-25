# Safety Architecture

The full, test-referenced account is `docs/safety-case.md` in the repo. This page is the operator-level summary.

## Principles

1. **The pilot's transmitter switch is the safety.** `FLTMODE_CH` changes the FC's mode through the RC receiver, a path that never touches the Pi. Everything in software sits on top of it, never instead of it.
2. **The flight controller is the flight authority.** The Pi only proposes velocity setpoints, and only while the FC is in `GUIDED`.
3. **One gate.** Every guidance command passes `SafetySupervisor.evaluate()`. Safety mechanisms work by feeding inputs into that gate, not by patching each controller.
4. **Never silent.** Every refusal or hold is sent to the app with a reason and shown as a banner.
5. **Fail closed.** Missing or stale data stops guidance rather than being assumed fine.
6. **Restart comes back idle.** No restart, crash or reconnect ever resumes guidance on its own.

## The Supervisor gate

Checked in this order every frame; the first failing check wins and forces `SAFE` (no guidance):

| # | Check | `guidance_reason` |
|---|---|---|
| 1 | Any required subsystem stale for > 2 s: `camera`, `tracker`, `mavlink`, `comms`, `rc_channels` | `stale_subsystems:<names>` |
| 2 | Pilot stick deflection beyond the deadband (0.15) | `rc_override` |
| 3 | FC reports a geofence breach (Approach-Test handles this itself) | `geofence_breached` |
| 4 | Battery ≤ 20 % | `battery_critical` |
| 5 | Any detected object closer than 2 m | `obstacle_too_close:<class>:<m>m` |
| 6 | Operator link silent for 3 s | `comms_lost` |
| 7 | FC not in `GUIDED` | `fc_not_in_ai_mode` |
| 8 | Target lost while Follow/Orbit/Approach requested | `target_lost` |

Only Follow, Orbit, Approach, Searching and Grid Search can be "allowed". Searching is exempt from check 8 (target loss is its trigger); Grid Search is exempt too (it never tracks a target).

On top of the gate, guidance **holds** (zero velocity, `guidance_hold`) when the target has been unseen ≥ 0.3 s, its identity is in doubt, the aircraft is still climbing, or GPS is degraded in Grid Search.

## Mechanisms

### RC override

- **Hardware** (the guarantee): `FLTMODE_CH` switch → FC mode changes directly. Must work with the Pi off; verified 20/20 on the bench before any flight.
- **Software backstop**: `RcOverrideMonitor` watches `RC_CHANNELS` for stick deflection. It stops guidance and, if the FC is still in `GUIDED`, requests `LOITER` once, because GUIDED ignores the sticks.
- **Fails closed**: if `RC_CHANNELS` stops arriving, `rc_channels` goes stale and guidance stops.
- The Pi never requests a mode (GUIDED, RTL, BRAKE) or retries one while the pilot is moving the sticks.

### Operator STOP

Stops all guidance, forgets the target, cancels searches and sweeps, and commands **BRAKE** (hold position) - not while the pilot has stick override. Guidance only restarts when the operator deliberately re-engages `GUIDED` and a mode.

### Operator link

- The app pings every 500 ms. 3 s of silence → `comms_lost` (guidance stops), even if the TCP socket still looks open.
- **15 s** continuous loss while armed and in `GUIDED` → the Pi requests **RTL once** per episode. Not under stick override, and never again after the pilot changes mode.
- A phone that falls ~1 s behind on updates is disconnected (code 1013) and counts as lost until it reconnects, so the control loop never waits on it.

### Battery

≤ 20 % → guidance stops, and RTL is requested once if the Pi holds the aircraft in `GUIDED`. Arm & Follow refuses to take off at ≤ 30 %. An unknown battery reading never trips this - the FC's own battery failsafe must be configured as the primary protection.

### Geofence

A fence breach reported in `SYS_STATUS` stops all guidance and aborts Approach-Test. Wired, but **not yet confirmed against a real FC's fence**.

### Obstacles

Any detected object (not just the target) estimated closer than 2 m stops guidance. **Vision-only and class-based**: it sees people, vehicles and the like, not walls, trees, poles, wires or glass. Fly only in open areas.

### GPS

Grid Search needs a fresh (< 2 s) position, fix type ≥ 3 and HDOP ≤ 2.5, or it holds. Arm & Follow refuses takeoff on a bad reported fix.

### Altitude and speed

2 m floor and 30 m ceiling in every vertical mode; descent is suppressed when altitude is unknown or stale. Speed and acceleration are capped. App-supplied values are clamped to config bounds.

### Force disarm

A forced disarm cuts motors whatever the FC thinks. It is refused above 1.5 m when altitude is known, and reported as a rejected disarm.

### Target loss

Follow/Orbit: a bounded search, then RTL by default, or landing **only with explicit operator approval**. See [Guidance Modes → Target-loss recovery](Guidance-Modes#target-loss-recovery).

### Frame-loop stalls

A gap over 0.5 s between frames resets the controllers instead of feeding a huge time step into PIDs and acceleration limits.

## Process and link recovery

| Failure | Detection | Response |
|---|---|---|
| Exception while processing one frame | caught per frame | Frame skipped (no command), loop continues |
| Malformed MAVLink or app message | caught per message | Message dropped, link continues |
| **MAVLink read or write error** | error on the port | Link closed and reopened with backoff (0.5 s up to 5 s), forever; FC streams requested again; writes during the gap report failure instead of raising |
| **MAVLink silent 5 s** | receive timeout | Same reopen (guidance already stopped at 2 s) |
| **Camera stops delivering frames** | no frame for 2 s (15 s at start) | Process exits with status 3; systemd restarts it in IDLE |
| **Event loop frozen / perception loop stalled** | no watchdog ping for 10 s | systemd kills (SIGABRT) and restarts |
| Process crash | exit | systemd restarts after 2 s, never gives up |
| Never becomes ready at boot | no READY in 120 s | systemd restarts |

While the companion is down, no setpoints arrive, and the FC's `GUID_TIMEOUT` makes it hold position. **It does not land** - the pilot must take over with the switch.

## Known limits (accept these explicitly before flying)

1. Obstacle detection is vision-only and class-based.
2. Identity matching is colour-based; similar clothing can confuse it.
3. A dead Pi or camera leaves the aircraft holding in GUIDED, not landing.
4. RTL flies a straight line at `RTL_ALT` - check the path is clear.
5. Geofence and every MAVLink behaviour are tested against a mock FC, not yet against real ArduPilot fence/mode behaviour.
6. Recovery's "can it make it home" estimate uses placeholder constants.
7. The camera calibration is a placeholder.
8. No SITL or flight test of these behaviours yet.

## Where it is tested

Every gate has a test that trips only that condition. Key test files: `test_safety_supervisor.py`, `test_failsafes_and_freshness.py`, `test_tracking_safety_orchestrator.py`, `test_admin_commands.py`, `test_target_recovery*.py`, `test_approach_test.py`, `test_mavlink_reconnect.py`, `test_transport_slow_client.py`, `test_camera_stall.py`, `test_service_watchdog.py`, `test_safety_parameters.py`. See [Simulation and Testing](Simulation-and-Testing).
