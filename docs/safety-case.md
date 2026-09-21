# Safety Case

Status: living document, first written 2026-09-19 - reflects what's
actually implemented and tested today, not the aspirational end state.
Update this whenever a safety-relevant mechanism changes; treat a stale
entry here as worse than no entry.

Every guidance controller (Follow, Orbit, Approach-Test, Dronie/Parabola)
only ever *proposes* a velocity setpoint. `SafetySupervisor.evaluate()`
(`companion/safety/supervisor.py`) is the single point that decides whether
that setpoint is actually allowed to reach `MavlinkBridge.send_velocity_
setpoint()` - every mechanism below works by feeding an input into that one
gate, not by patching guidance code individually. `SupervisorDecision.reason`
is sent to the Android app in every `tracking_update` message and rendered
as a visible on-screen warning (`GuidanceWarningBanner.kt`) - a triggered
mechanism is never silent to the operator.

## RC override (hardware path)

- **Mechanism**: the pilot's transmitter has a hardware mode switch mapped
  to `FLTMODE_CH` on the flight controller. Flipping it changes the FC's
  flight mode through the RC receiver directly - this path physically
  never passes through the Pi, so it works even if the companion computer
  is frozen, crashed, or powered off entirely. This is the actual
  guarantee this whole project is built around; everything else here is a
  software backstop on top of it.
- **Software backstop**: `RcOverrideMonitor.is_overriding()`
  (`companion/mavlink/rc_monitor.py`) watches `RC_CHANNELS` for stick
  deflection beyond a deadband while AI guidance is active, and
  `SafetySupervisor.evaluate()` forces `SAFE` (reason `"rc_override"`) the
  moment it sees this - independent of and in addition to the hardware
  path above.
- **What this does and does not guarantee**: the hardware switch is
  guaranteed to work regardless of Pi state. The software stick-deflection
  backstop is a convenience for "the pilot grabbed the sticks without
  touching the mode switch" - it depends on the Pi being alive and reading
  `RC_CHANNELS`, so it is explicitly *not* a substitute for the hardware
  switch.
- **A real bug found in a code-review audit, now fixed**: target-loss
  recovery's automatic RTL (`companion/main.py`, see "Follow/Orbit-only"
  below) fired `mavlink.set_mode("RTL")` unconditionally when its search
  timed out - even if the pilot had already taken RC stick override
  mid-search. That contradicted "RC override always takes precedence": the
  pilot was already flying manually at that point, and an autonomous RTL
  had nothing useful to override, only something to yank away. RTL is now
  suppressed whenever `rc_override_active` is true at the moment the
  timeout fires (`test_rtl_is_suppressed_while_pilot_has_rc_override`).
  This is the one place in this project where an override-adjacent
  decision lived outside `SafetySupervisor.evaluate()` itself (RTL is a
  direct FC mode change, not a velocity setpoint, so it was never gated by
  it) - worth remembering if a similar direct-mode-change path is ever
  added elsewhere.
- **A related known gap, deliberately not fixed here**: the software
  backstop's fail-safe direction assumes `RC_CHANNELS` keeps arriving. If
  a real FC only streams the legacy `RC_CHANNELS_RAW` message, or
  `RC_CHANNELS` stops arriving mid-flight for any reason,
  `telemetry.rc_channels` stays at its last value (or empty) and
  `is_overriding()` silently keeps returning `False` forever - a stuck
  backstop that looks alive. This wasn't fixed because it changes RC-
  override safety semantics (e.g. what should "no RC telemetry" *do* -
  fail open, force `SAFE`, or something else) and needs a decision plus
  real-hardware validation, not just a mechanical patch. Flagged here so
  it isn't lost - the hardware switch above is what actually makes this
  gap non-critical in practice.
- **Status**: software backstop implemented and unit/integration tested.
  **The hardware switch itself is not yet configured on the transmitter**
  (`FLTMODE_CH` param) - see root README "What's next" #4. Until that's
  done, the actual non-negotiable guarantee this project depends on is not
  live on real hardware yet, only the software approximation of it is.
  **`docs/flight-readiness-checklist.md`** has the exact step-by-step
  procedure for configuring and verifying it (including the plan's own
  20/20-trials acceptance criteria), plus the props-off guidance dry-run
  that comes right after.
- **Tests**: `test_rc_monitor.py` (deadband logic in isolation),
  `test_safety_supervisor.py::test_rc_override_forces_safe`,
  `test_approach_test.py::test_rc_override_aborts`,
  `test_integration_sim.py::test_follow_mode_sends_setpoints_then_rc_override_halts_them`
  (real MAVLink `RC_CHANNELS` from a mock FC, through the real bridge, to a
  real halted setpoint stream) - all passing.

## Operator abort (the app's STOP/ABORT button)

- **Mechanism**: `CompanionOrchestrator._on_abort()` (`companion/main.py`)
  does two things, not just one. It always stops every guidance-side
  concept immediately (`requested_mode = IDLE`, stops Approach-Test/smart
  shot, stops the tracker, forgets the appearance-reid memory, cancels an
  in-progress target-loss search) - this alone stops the Pi from sending
  any further velocity setpoints. On top of that, it now also actively
  commands `mavlink.set_mode("BRAKE")` - ArduCopter's dedicated "stop now
  and hold this exact position" mode - rather than relying on ArduPilot's
  own GUIDED-mode setpoint-timeout to passively notice the setpoint stream
  went quiet and hold position several seconds later. Abort is a
  deliberate, explicit operator safety action; it gets an equally
  immediate, explicit response.
- **RC-override suppression**: same reasoning as the target-loss RTL
  suppression above - if the pilot already has RC override active at the
  moment Abort is pressed, they're already flying manually, so a
  `set_mode("BRAKE")` here would fight their own control instead of
  helping. `_on_abort()` checks `RcOverrideMonitor.is_overriding()` against
  the current `RC_CHANNELS` and skips the mode change (but still does the
  guidance-side stop) when it's true. Also skipped with no real MAVLink
  connection at all (e.g. sim/unit tests that never call
  `MavlinkBridge.connect()`).
- **How it resumes**: BRAKE holds until the operator deliberately takes
  further action - either the pilot's own `FLTMODE_CH` hardware switch (as
  always, entirely independent of the Pi), or, from the app, explicitly
  setting the FC back to `GUIDED` (`set_flight_mode`) before selecting an
  AI mode again. The Pi never re-engages `GUIDED` on its own - matches how
  AI guidance was already never allowed to auto-start from `IDLE`
  (`SafetySupervisor` gates on `fc_mode == "GUIDED"`, see M7/M10) - so this
  needed no new gating logic, just the existing precondition already doing
  its job.
- **Tests**: `test_abort_commands_brake_to_hold_position`,
  `test_abort_suppresses_brake_during_rc_override`
  (`test_admin_commands.py`) - both against a real (mocked-transport)
  `MavlinkBridge.set_mode_send()` call. Not yet confirmed against a real
  FC's actual BRAKE-mode behavior.

## Target-loss handling

- **Mechanism**: `TrackingStateMachine` (`companion/tracking/state.py`)
  distinguishes a brief in-frame stumble (`REACQUIRE`, IoU/motion-based,
  `reacquire_timeout_s` default 2.0s) from a genuine `TARGET_LOST`. Once
  `TARGET_LOST`, `SafetySupervisor.evaluate()` forces `SAFE` (reason
  `"target_lost"`) for any requested guidance mode - stale target
  coordinates are never fed into a guidance controller.
- **Appearance-based reacquisition** (`companion/tracking/appearance.py`)
  can auto-relock the same target after `TARGET_LOST` by color-histogram
  similarity, but only ever *proposes* a re-selection the same way a
  fresh operator tap would - it does not bypass this gate.
- **Guarantee**: no guidance command is ever computed from a target that
  the tracker has stopped confidently reporting on.
- **Tests**: `test_state_machine.py` (REACQUIRE/TARGET_LOST timing),
  `test_safety_supervisor.py::test_target_lost_forces_safe_when_guidance_requested`
  and `::test_target_lost_does_not_block_plain_tracking_request`,
  `test_approach_test.py::test_target_lost_aborts`,
  `test_appearance_reacquire.py` (the reacquisition path itself, including
  that abort clears the remembered target instead of silently relocking
  it) - all passing.

### Follow/Orbit-only: bounded search, then RTL or an operator-confirmed landing

The forced-`SAFE` behavior above is the whole story for Approach-Test and
Dronie/Parabola - deliberately unchanged, since those modes are already
stricter about target loss (Approach-Test aborts immediately; a smart
shot has a fixed duration and finishing early on loss is fine). Follow and
Orbit get an additional layer on top, since those are the modes meant to
keep an aircraft near a target for an extended period, where "just stop
and hold forever" is a worse outcome than trying to recover, then a
graceful fallback:

- **Mechanism**: `TargetRecoveryController`
  (`companion/guidance/target_recovery.py`), engaged by
  `CompanionOrchestrator.process_frame()` only when `TARGET_LOST` occurs
  while `requested_mode` is `FOLLOWING` or `ORBITING`:
  1. **Search** (`search_timeout_s`, default 60s): a bounded yaw-only
     sweep (`search_yaw_rate_rads`, alternating direction every
     `sweep_half_period_s` rather than spinning continuously, staying
     roughly oriented toward where the target was last seen) - this is a
     new `SupervisorState.SEARCHING` guidance path, gated by
     `SafetySupervisor.evaluate()` exactly like Follow/Orbit/Approach-Test
     (RC override, comms loss, obstacle proximity, stale subsystems all
     still apply). If the target reappears (via the tracker's own
     REACQUIRE window or the appearance-rematch above), the search cancels
     and Follow/Orbit resumes normally with no operator action needed. The
     operator can also cancel it explicitly by commanding any mode other
     than Follow/Orbit (e.g. "Normal RC") - **a real bug found in a
     code-review audit**: only an explicit abort used to cancel an
     in-progress search, so switching modes away from Follow/Orbit left
     the yaw-sweep running to completion on its own timer regardless
     (`test_mode_command_away_from_follow_cancels_an_active_search`).
  2. **Decision** (if the search times out): RTL by default
     (`MavlinkBridge.set_mode("RTL")`, a direct FC mode change, not a
     guidance setpoint - same category as `arm()`/`set_mode()` already
     bypassing the velocity-setpoint gate, and **suppressed if the pilot
     has RC override active at that moment** - see "RC override" above).
     Only considers landing in place instead if battery is below
     `low_battery_pct_threshold` (default 20%) **and** an estimated
     RTL-feasibility check says the aircraft likely can't make it home -
     see the honest caveat on that estimate below. Missing telemetry (no
     GPS fix, no home position, no battery reading) always defaults to RTL
     rather than guessing at a landing decision with incomplete
     information.
  3. **Landing requires an explicit operator decision** - never automatic.
     A `land_confirmation_request` message (distance to home, battery,
     and whether the existing obstacle-proximity detector currently sees
     anything - informational only, not a veto) is sent once, and the
     aircraft holds (no guidance command) until a
     `land_confirmation_response` arrives. Only `{"approved": true}`
     triggers `set_mode("LAND")`; a denial (or no response) leaves the
     aircraft exactly where the FC's own behavior already puts it (e.g.
     GUIDED's setpoint-timeout hold). **A real bug found in a code-review
     audit**: the target-reacquired check was gated on the search still
     being active, but the timeout path clears that state the instant it
     decides to ask for a landing - a target that reappeared while a
     confirmation was outstanding was silently ignored, leaving the
     operator stuck answering a question about a target that was already
     back in view instead of just resuming Follow/Orbit
     (`test_reacquiring_target_while_awaiting_land_confirmation_resumes_follow`).
- **Distance-to-home**: `MavlinkBridge` requests a real `HOME_POSITION`
  message (`MAV_CMD_GET_HOME_POSITION`) once, on the arm transition, and
  parses ArduPilot's real reply - `companion/guidance/geo.py`'s haversine
  distance from that to current `GLOBAL_POSITION_INT` lat/lon feeds the
  RTL-feasibility estimate.
- **Honest caveat on the RTL-feasibility estimate**: it is NOT a
  live-measured battery drain rate (that needs a time series that takes a
  while to stabilize after boot) - it's `assumed_return_speed_mps` and
  `assumed_max_flight_time_s` (config constants, `target_recovery.yaml`)
  combined with a `rtl_safety_margin` multiplier. These are
  aircraft-specific placeholders and **must be tuned from real flight
  data** before this decision should be trusted - exactly the same
  category of "confirmed in code, not yet confirmed against real
  hardware" as the geofence signal above.
- **Guarantee**: a velocity command is only ever sent during the bounded
  search window, subject to every other Supervisor gate; RTL is always
  the default outcome; landing never happens without an explicit,
  freshly-requested operator approval for that specific event.
- **Tests**: `test_target_recovery.py` (the search/decision state machine
  in isolation - sweep timing/direction, reacquisition cancels search,
  RTL vs. land-confirmation decision under various battery/distance
  combinations, missing-telemetry defaults to RTL, confirmation doesn't
  re-request every frame), `test_geo.py` (haversine distance against known
  geodesy reference values), `test_mock_fc.py::test_bridge_receives_real_home_position_on_request`
  (a real `HOME_POSITION` reply over real MAVLink, using pymavlink's own
  confirmed `home_position_send` signature), `test_safety_supervisor.py::test_searching_is_allowed_even_though_target_is_lost`
  and `::test_searching_still_blocked_by_rc_override`,
  `test_target_recovery_orchestrator.py` (the full wiring: search engages
  and sends a yaw-only command, reacquisition resumes Follow, search
  timeout triggers RTL or a land-confirmation request depending on
  battery/distance, and the operator's approve/deny response) - all
  passing. **Not yet confirmed against real hardware** - every test here
  uses a mock FC or a mocked MAVLink connection, the same category of gap
  as everything else in this document flagged that way.

## Comms-loss handling (Android link)

- **Mechanism**: `GroundStationLink.is_connected` reflects whether the
  WebSocket transport currently has a connected client. `SafetySupervisor.
  evaluate()` forces `SAFE` (reason `"comms_lost"`) whenever it's False.
- **Guarantee**: guidance cannot continue running with no operator able to
  see telemetry or reach the abort button. It does **not** by itself stop
  the aircraft or trigger RTL - it stops new guidance setpoints from being
  sent, after which ArduPilot's own GUIDED-mode setpoint-timeout behavior
  (holds position once setpoints stop arriving) is the actual backstop -
  see "MAVLink link failure" below for why this project leans on that
  ArduPilot behavior rather than re-implementing it.
- **Tests**: `test_safety_supervisor.py::test_comms_lost_forces_safe`,
  `test_approach_test.py::test_comms_lost_aborts` - passing. Not yet
  tested against a real dropped WiFi link in the field (only the boolean
  flag path is exercised).

## MAVLink link / subsystem failure (watchdog)

- **Mechanism**: `HeartbeatWatchdog` (`companion/safety/watchdog.py`)
  tracks a last-seen timestamp per subsystem (`camera`, `tracker`,
  `mavlink`, `comms`). `SafetySupervisor.evaluate()` checks
  `REQUIRED_SUBSYSTEMS` first, before any other input, and forces `SAFE`
  (reason `"stale_subsystems:<names>"`) if any of them haven't reported in
  within `timeout_s`.
- **Camera failure** and **MAVLink failure** are both instances of this
  same mechanism, not separate code paths - if the camera stops producing
  frames or the MAVLink link stops delivering messages, the corresponding
  heartbeat goes stale and this gate trips.
- **Process-level backstop**: `deploy/ai-vision-drone.service`
  (`Restart=on-failure`) restarts the whole companion process if it
  crashes outright, always coming back up in `IDLE` - it never
  auto-resumes a guidance mode after a restart. `SystemdWatchdog`
  (`companion/safety/watchdog.py`) is wired to send `WATCHDOG=1` if
  `sdnotify` happens to be installed, but the unit intentionally uses
  `Type=simple` (not `Type=notify`) because the code never sends the
  `READY=1` notification `Type=notify` requires - so this specific
  systemd-level hang-detection path is not actually active today, only
  crash-restart is (see `docs/hardware-wiring.md` if this needs revisiting).
- **Guarantee**: guidance stops within one `HeartbeatWatchdog.timeout_s`
  window of any required subsystem going quiet, not just on an outright
  exception.
- **Tests**: `test_watchdog.py` (staleness logic in isolation),
  `test_safety_supervisor.py::test_stale_subsystem_forces_safe` (a genuine
  fault-injection style test: only 3 of 4 required subsystems beaten) -
  passing. Not yet a live power-cycle/kill-the-process test on real
  hardware (see README M15 status).

## Obstacle proximity (cross-mode, not target-specific)

- **Mechanism**: `check_proximity()` (`companion/safety/proximity_guard.py`)
  runs against *every* detection each frame, not just the tracked target,
  using the same vision distance estimator Follow/Orbit already use.
  `SafetySupervisor.evaluate()` forces `SAFE` (reason
  `"obstacle_too_close:<class>:<distance>m"`) if anything is estimated
  closer than `min_obstacle_distance_m` (`companion/config/safety_limits.yaml`,
  default 2.0m) - checked before comms/FC-mode/target-loss, right after RC
  override.
- **Guarantee**: an untracked obstacle closing in (a wall, a second
  person, a vehicle) halts guidance exactly like the followed subject
  itself getting too close would.
- **Explicit limitation**: this inherits the vision-only distance
  estimator's accuracy caveats (docs plan M4) - it is a software
  convenience layer, not a certified collision-avoidance system, and
  should not be treated as sufficient justification for operating without
  a spotter or without maintaining a safe real-world margin yourself.
- **Tests**: `test_proximity_guard.py` (detection/distance logic in
  isolation, including "closest of several" and "unknown class safely
  skipped"), `test_safety_supervisor.py::test_obstacle_too_close_forces_safe`
  and `::test_obstacle_alert_takes_priority_over_comms_lost_reason` -
  passing.

## Controlled Approach-Test abort conditions

- **Mechanism**: `ApproachTestController` (`companion/guidance/approach_test.py`)
  independently checks target-loss, comms-loss, RC override, and geofence
  breach every update - any one alone is sufficient to move it to
  `ABORTED`, and reaching `min_boundary_m` or a real contact-sensor signal
  moves it to `STOPPED_AT_BOUNDARY` (holds position, does not continue).
  Both are terminal until the operator explicitly restarts or leaves the
  mode - this is intentional: an approach-test boundary event is
  significant enough that it should require a conscious operator decision
  about what happens next, not silently clear itself (contrast with
  Dronie/Parabola smart shots below, which *do* self-clear since they have
  no comparable safety significance once finished).
- **Geofence signal wiring**: `companion/main.py` now reads
  `self.mavlink.telemetry.fence_breached` instead of a hardcoded `False`.
  That field is parsed in `MavlinkBridge._handle_message()` from a real
  `SYS_STATUS` message's `onboard_control_sensors_enabled`/`_health`
  bitmasks, gated on pymavlink's own `MAV_SYS_STATUS_GEOFENCE` constant
  (not a hand-guessed bit shift) - this is standard, documented
  ArduPilot/MAVLink behavior (a fence has no dedicated status message; its
  state rides on `SYS_STATUS`'s generic sensor-health bits).
- **Remaining honest gap**: this has been verified against a real
  `MavlinkBridge` and a (mock) FC sending real `SYS_STATUS` messages over
  real UDP (`test_mock_fc.py::test_bridge_reflects_a_real_geofence_breach_over_real_mavlink`),
  and against the full orchestrator wiring
  (`test_approach_orchestrator.py`) - but, like every MAVLink integration
  in this project, **it has not been confirmed against a real ArduPilot FC
  yet**. The mock only emits the bits this code expects to see; it does
  not prove a real Cube Orange reports geofence status the same way. Given
  this project's own history of a MAVLink assumption turning out wrong in
  a way only real hardware revealed (the TELEM baud-rate saga, see
  `docs/hardware-wiring.md`), **do not treat this as load-bearing for a
  real flight until it's been confirmed against the real FC** (e.g. by
  enabling `FENCE_ENABLE` on the bench and confirming
  `telemetry.fence_breached` flips when the boundary is crossed).
- **Tests**: the full `test_approach_test.py` suite (every abort condition
  individually, plus `test_aborted_state_persists_until_restart` and
  `test_contact_sensor_stops_regardless_of_distance`) at the controller
  level; `test_mock_fc.py` and `test_approach_orchestrator.py` for the
  real-MAVLink-to-orchestrator wiring above - all passing. No SITL or
  bench test of the full chain has been run yet (docs plan M9's own
  required next step).

## One-shot smart shots (Dronie/Parabola) - a deliberately different design

- Unlike the above, a finished smart shot has no residual safety
  significance, so `companion/main.py` resets `requested_mode` to `IDLE`
  the moment `SmartShotController` reports `FINISHED`, and the Android app
  mirrors this by reverting its own mode selector - see
  `test_smart_shot_command.py::test_smart_shot_finishes_after_its_duration`.
  This is called out here specifically so it isn't mistaken for an
  inconsistency with Approach-Test's deliberately-sticky behavior above -
  it's a considered difference, not an oversight.

## Fault-injection test coverage summary

Every mechanism above that has a corresponding `SafetySupervisor` gate is
covered by at least one test that independently trips *only that
condition* and asserts guidance is denied - this is what "fault injection"
means in this codebase's test suite, not a separate framework. As of this
writing: 207 companion tests passing
(`.venv/Scripts/python -m pytest -q`), including a real end-to-end test
(`test_integration_websocket.py`) that drives the actual JSON wire
protocol over a real WebSocket and real MAVLink link, and real-MAVLink
mock-FC tests for arm/set-mode/geofence-status (`test_mock_fc.py`) - not
just in-process Python calls.

## What this document does not yet cover

- `companion.main` has now been run in hardware mode with a real FC
  connected live (camera, on-sensor AI, video, and MAVLink all running
  together, not proven separately as before) - heartbeat, telemetry,
  arm/disarm, and flight-mode read/set were confirmed against the real FC.
  **No guidance setpoint (Follow/Orbit/Approach-Test) has been sent to the
  real FC yet** - only administrative commands and read-only telemetry
  have been exercised on real hardware so far. Don't read "hardware mode
  confirmed working" anywhere in this project as covering guidance output;
  it doesn't yet.
- No real SITL (ArduPilot software-in-the-loop) run exists for this
  project - `sim/mock_fc.py` is a lightweight MAVLink emulator, not real
  ArduPilot flight dynamics (see `sim/README.md`).
- **A bench test (props off, on the mounted aircraft) has now been done** -
  M14 stage 1, confirming the full stack (camera, AI, video, MAVLink) runs
  together on the actual airframe. This was explicitly a no-motion,
  no-guidance-engaged step: it did not exercise the abort chain, and no
  guidance controller was engaged, so it says nothing about whether
  Follow/Orbit/Approach-Test can actually drive the real FC safely - that
  is still the next, separate bench session to run, now with the live
  dashboard (`tracking_update`'s `commanded_vx_mps`/`vy_mps`/`vz_mps`/
  `yaw_rate_rads`/`guidance_sent`, Android's `GuidanceCommandPanel`) ready
  to watch while props stay off.
- No real-flight test (motors spinning, aircraft airborne) has occurred.
  Per the plan's staged sequence (M14): stage 1 (bench, props off, done
  above) and stage 2 (tethered/ground hover, Normal RC, Pi passive - no AI
  guidance active) don't depend on `FLTMODE_CH` or the geofence signal at
  all, since the Pi isn't driving anything yet in either. Stage 3 (free
  flight, Normal RC, AI Tracking active but not driving) is the same.
  **`FLTMODE_CH` and the real-ArduPilot-confirmed geofence signal become
  load-bearing starting at stage 4** (Follow-mode actually flying) - that
  stage, and everything after it, is correctly gated on both being closed
  first; stages 1-3 are not.
- **Two known gaps found in a code-review audit, deliberately not fixed
  yet** (beyond the RC_CHANNELS-staleness one under "RC override" above):
  - `SessionRecorder.record()` (`companion/logging_/session_recorder.py`)
    does a synchronous file write + flush on every call, from inside the
    async per-frame hot loop, with no executor offload. Several calls can
    fire within a single frame (an obstacle alert, a guidance command,
    etc.), and on Pi SD/eMMC storage under contention (e.g. concurrent
    video recording) each flush is a blocking syscall that can stall
    MAVLink receive and WebRTC delivery for its duration. Not fixed here
    because a safe fix needs either an async-aware logging path or an
    explicit durability trade-off (buffered writes vs. crash-safety for a
    safety-relevant flight log) - not a mechanical patch, and `record()`
    is called from many synchronous, non-awaitable callback sites.
  - `DistanceEstimator.estimate()` (`companion/guidance/distance.py`)
    returns a single rangefinder reading for every detection in the frame
    it's asked about, not specifically the tracked target's own distance.
    Currently unreachable in practice - `RangefinderSource.__init__`
    always raises `NotImplementedError`, since the M4 rangefinder hasn't
    been purchased yet (see root README) - but once real rangefinder
    hardware is wired up, this would make `check_proximity()` report the
    tracked target's distance for every object in frame, including
    untracked obstacles at a genuinely different distance, silently
    defeating the obstacle-proximity check for anything not being
    tracked. Flagged here now so it isn't rediscovered the hard way when
    the rangefinder decision is finally made - fixing it needs a product
    decision (e.g. only trust the rangefinder reading for the actively
    tracked target, fall back to vision-only for everything else), not
    just a mechanical patch.
