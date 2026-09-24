# Safety Case

Status: living document, first written 2026-09-19 - reflects what's
actually implemented and tested today, not the aspirational end state.
Update this whenever a safety-relevant mechanism changes; treat a stale
entry here as worse than no entry.

Every guidance controller (Follow, Orbit, Approach-Test, Grid Search)
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
- **A related known gap, now fixed**: the software backstop's fail-safe
  direction used to assume `RC_CHANNELS` keeps arriving. If a real FC only
  streamed the legacy `RC_CHANNELS_RAW` message, or `RC_CHANNELS` stopped
  arriving mid-flight for any reason, `telemetry.rc_channels` would stay at
  its last value (or empty) and `is_overriding()` would silently keep
  returning `False` forever - a stuck backstop that looks alive. This
  needed an explicit decision on what "no RC telemetry" should do (fail
  open, force `SAFE`, or something else) before it could be fixed, not just
  a mechanical patch - the decision made: fail closed, consistent with
  every other subsystem this project already treats this way. `rc_channels`
  is now a required subsystem in `SafetySupervisor.REQUIRED_SUBSYSTEMS`
  alongside camera/tracker/mavlink/comms, beaten specifically on a real
  `RC_CHANNELS` message (`CompanionOrchestrator._on_mavlink_message`, not
  on arbitrary MAVLink traffic) so its staleness is detected independently
  of the broader MAVLink-link-alive heartbeat - if `RC_CHANNELS`
  specifically stops arriving, the Supervisor now forces `SAFE`
  (`stale_subsystems:rc_channels`) even while other MAVLink messages keep
  flowing. Unit-tested (`test_safety_supervisor.py::
  test_stale_rc_channels_forces_safe`, `test_admin_commands.py::
  test_on_mavlink_message_beats_rc_channels_only_for_that_message_type`).
- **A field-reported UX gap, now fixed - the Pi automatically requests
  GUIDED**: found during real `FLTMODE_CH` bench testing - selecting a
  target and choosing a guidance mode (Follow/Orbit/Approach/Grid Search)
  used to do nothing observable until the pilot separately switched the FC
  to GUIDED themselves, since `SafetySupervisor.evaluate()`'s
  `fc_not_in_ai_mode` check silently refused the mode otherwise.
  `CompanionOrchestrator._on_mode_command()` (`companion/main.py`) now
  calls `mavlink.set_mode("GUIDED")` itself when the operator selects one
  of those modes - but only when `MavlinkBridge.is_connected`, the FC
  isn't already in GUIDED (idempotent), **and `rc_override_active` is
  false** - this is the same override-adjacent direct-mode-change path
  called out above for RTL, gated by the exact same check for the exact
  same reason: the pilot may already be flying manually at that moment,
  and a mode change from the Pi would fight their own control rather than
  help. This does not change what the hardware `FLTMODE_CH` switch itself
  guarantees in any way - it only ever *requests* GUIDED through the same
  MAVLink path any GCS would use, and the FC (or the pilot's own switch)
  remains entirely free to refuse or immediately override it. Unit-tested
  (`test_mode_command.py::test_selecting_follow_automatically_requests_guided`,
  `::test_every_mode_requiring_guided_requests_it`,
  `::test_auto_guided_is_never_requested_while_rc_override_is_active`,
  `::test_auto_guided_is_a_no_op_when_already_in_guided`).
  The hardware switch above remains the actual non-negotiable guarantee;
  this only closes the gap in the software-only backstop.
- **A real, more significant field-reported gap, now fixed - the software
  backstop actually requests LOITER**: ArduCopter's GUIDED mode does not
  respond to RC stick input for attitude/velocity control at all - that is
  the entire point of GUIDED, external control only. This means the
  software backstop's own action up to this point (stopping this Pi's
  velocity setpoints the moment `rc_override_active` goes true) did *not*
  actually hand the pilot back a flyable aircraft while `fc_mode` was still
  `GUIDED` - the FC just held position via GUIDED's own setpoint-timeout
  behavior, deaf to the sticks, which could look and feel exactly like a
  working override without one actually having happened. `process_frame()`
  now also calls `mavlink.set_mode("LOITER")` (a real manual-ish mode that
  *does* respond to sticks) the moment it sees stick override while
  `fc_mode == GUIDED` - edge-triggered (once per transition into that
  state, not every frame, to avoid spamming a mode-change command) and
  re-checked against `fc_mode == GUIDED` every time, so if the pilot has
  already moved `FLTMODE_CH` themselves to some other mode, this never
  touches their own choice. This does not change the hardware switch's own
  guarantee in any way - it closes a real functional gap in what the
  *software* backstop actually accomplished when it fired. Unit-tested
  (`test_admin_commands.py::test_rc_override_while_guided_requests_loiter`,
  `::test_rc_override_loiter_request_is_edge_triggered_not_spammed`,
  `::test_rc_override_while_already_out_of_guided_never_requests_loiter`,
  `::test_no_rc_override_never_requests_loiter`,
  `::test_rc_override_loiter_request_re_fires_after_override_clears`).
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

The forced-`SAFE` behavior above is the whole story for Approach-Test -
deliberately unchanged, since it's already stricter about target loss
(it aborts immediately on TARGET_LOST). Follow and Orbit get an additional
layer on top, since those are the modes meant to
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
- **A camera that hangs** is a separate case: the frame loop itself stops,
  so nothing evaluates the gate above at all (no setpoints are sent either -
  the FC's `GUID_TIMEOUT` holds). Capture now runs on its own thread; no frame
  for `camera.stall_timeout_s` (2 s) raises `CameraStallError` and the process
  exits (status 3) for systemd to restart it.
- **Process-level backstop**: `deploy/ai-vision-drone.service`
  (`Type=notify`, `WatchdogSec=10`, `Restart=always`) restarts the whole
  companion process whenever it ends, always coming back up in `IDLE` - it
  never auto-resumes a guidance mode after a restart. `SystemdWatchdog`
  (`companion/safety/watchdog.py`, its own `sd_notify` - the `sdnotify`
  package it used to rely on was never a dependency, so the old watchdog
  silently did nothing) sends `READY=1` once the first frame has gone
  through the pipeline, then `WATCHDOG=1` only while a frame has completed
  within `pipeline_max_frame_age_s` (5 s). A frozen event loop or a stalled
  perception loop stops the pings and systemd kills and restarts the service.
  Confirmed against real systemd (a transient `Type=notify` unit under WSL:
  READY accepted, then `Result=watchdog` once pings stopped) - not yet on the
  Pi itself (lab checklist 10.7-10.8).
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
  about what happens next, not silently clear itself (contrast with a
  finished Grid Search sweep below, which *does* self-clear since it has
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

## Auto-takeoff sequencing (Arm & Follow gain-height-first gap)

- **Field-reported gap**: the "Arm & Follow" quick action used to arm and
  immediately engage Follow, which computes a horizontal approach-vector
  setpoint toward the tracked target with the aircraft still sitting on
  the ground - no vertical safety margin at all.
- **Mechanism**: `AutoTakeoffController` (`companion/guidance/auto_takeoff.py`)
  is a one-shot sequencer, not a guidance controller - it never computes a
  velocity command itself. `_on_mode_command()` starts it only when the app
  opts in via `auto_takeoff: true` on the mode_command (currently only
  "Arm & Follow"). While active, it holds `process_frame()`'s real
  guidance dispatch to a no-op (`command` stays `None` regardless of what
  `SafetySupervisor.evaluate()` would otherwise allow) until: (1) armed and
  in GUIDED - then it sends one `MAV_CMD_NAV_TAKEOFF` for
  `auto_takeoff_limits.yaml`'s `altitude_m`, the same standard
  ArduCopter GUIDED-mode takeoff a real GCS's "Takeoff" button sends, and
  ArduCopter itself climbs autonomously from there, no setpoints needed
  from this companion during the climb; (2) `telemetry.alt_m` reaches that
  altitude within `altitude_tolerance_m` - only then does the real
  requested guidance controller (Follow, currently the only mode that
  requests this) start computing and sending setpoints, same frame.
- **Fail-safe on a stuck climb**: if altitude is never reached within
  `timeout_s` (default 30s - e.g. a rejected `NAV_TAKEOFF` the app never
  saw, or a pre-arm check silently holding it on the ground), the
  sequence gives up and falls back `requested_mode` to `IDLE` rather than
  holding a guidance mode that never actually starts guiding, mirroring
  the rejected-grid-search-start failure mode.
- **Interaction with existing gates**: unaffected by and orthogonal to
  RC override, the target-lost/obstacle/comms-lost gates, and the
  auto-GUIDED-request feature above - those all still apply normally
  once auto-takeoff hands off to real guidance; a mode switch away or an
  explicit Abort mid-sequence calls `reset()` so a takeoff planned for one
  mode never silently carries over to whatever was picked instead.
- **Android-side correctness note**: `supervisor_state` on `tracking_update`
  reaches `"FOLLOWING"` immediately (the Supervisor itself has no reason to
  refuse it), but `guidance_sent` stays `false` for the whole climb - the
  app's `emitTrackingAlerts()` was fixed to gate the "Following target"
  voice/tone alert on `guidance_sent` catching up, not on `supervisor_state`
  alone, so it no longer fires while the aircraft is still climbing
  vertically with no horizontal guidance active yet.
- **Tests**: `test_auto_takeoff.py` (the state machine in isolation - every
  phase transition, the `update()` return-value contract, the timeout path
  from both `WAITING_TO_ARM` and `CLIMBING`, `reset()`/`start()` behavior)
  and `test_auto_takeoff_orchestrator.py` (the real wired sequence through
  `process_frame()`: held with no takeoff sent while unarmed, takeoff sent
  exactly once on the armed+GUIDED edge, held through the climb, real
  Follow guidance starting the same frame altitude is reached, the
  timeout-to-idle path, and reset-on-mode-switch/reset-on-abort) - all
  passing.

## Guidance limit enforcement and tracking identity (safety audit)

- **Found: configured limits that nothing enforced.** `follow_limits.yaml`
  and `orbit_limits.yaml` declared `max_accel_mps2`, `min_altitude_m`,
  `max_altitude_m`, `min/max_separation_m` and `min/max_radius_m`, but a
  search of the whole codebase (Pi and Android) found no code reading any of
  them. Pixel-framing vertical control in particular had no altitude floor:
  a target below the image center commanded a descent for as long as it
  stayed there.
- **Mechanism now**: `guidance/limits.py` - `SlewLimiter` (acceleration cap
  on vx/vy/vz, reset whenever a controller did not run, so guidance resuming
  after RC override / SAFE / a hold ramps from standstill), and
  `apply_altitude_limits()` (refuses a descent at or below `min_altitude_m`
  and a climb at or above `max_altitude_m`; with no altitude telemetry,
  descent is suppressed and climbing allowed). Applied last in
  `FollowController`/`OrbitController.compute()` after the speed clamp, then
  the speed clamp is re-applied so a live `set_max_speed()` decrease takes
  effect immediately despite the ramp.
- **App-supplied values are clamped on the Pi** (`_on_mode_command`) to those
  same bounds, and non-finite/non-numeric values (JSON permits `NaN`) are
  ignored; grid-search width/height are bounded by
  `grid_search_limits.yaml`'s `min/max_dimension_m`. The Android sliders
  already stay inside these ranges - the Pi no longer depends on that.
  `run_startup_health_check()` refuses to boot if any enforced key is
  missing, so a config typo can no longer silently disable a limit.
- **No driving on frozen coordinates**: while the tracker is in REACQUIRE,
  `state_machine.target` still holds the last box, and Follow/Orbit used to
  keep computing from it (constant yaw rate, constant forward speed, for up
  to `reacquire_timeout_s`). They now command zero velocity once the target
  has been unseen for `target_hold_after_unseen_s` (0.3 s) - see "Safety pass:
  detection flicker, link and process recovery" below for why not on the very
  first missed frame (Approach-Test already aborted on this).
- **Tracking identity**: the IoU tracker follows whichever box overlaps its
  prediction, so two people crossing could silently swap the followed
  subject. `AppearanceMemory.check_identity()` compares the tracked box to
  the remembered appearance every frame (real camera frames only). After
  `track_swap_frames` consecutive mismatches it switches to a same-class
  detection that clearly matches the remembered look; after
  `track_drop_frames` with no such candidate it drops the lock to REACQUIRE
  (the drone holds) rather than pursue a probable stranger. A brief
  mismatch (turning around, shade) resets the counter on recovery.
- **Distance for Follow/Orbit** uses an upright person's height (steadier
  than width), refuses a border-clipped box (which would read as further
  than reality and make Follow close in), and is median/EMA-filtered.
  Obstacle proximity deliberately keeps the width-only estimate, which is the
  more conservative read for a "too close" check.
- **The operator is told why the drone stopped**: a deliberate hold is not a
  Supervisor block, so `guidance_reason` stays `null` - without more, a drone
  holding position looked identical to a failed one. `tracking_update` now
  carries `guidance_hold` (`auto_takeoff` / `target_unseen` / `identity_lost`),
  which the Android app shows as a banner and announces once when the hold
  begins. Tested in `test_tracking_safety_orchestrator.py`.
- **Known limits, stated plainly**: appearance matching is a color histogram
  - two people in similar clothing can still be confused, which is why a
  mismatch that has no confident alternative *stops* rather than guesses;
  thresholds are conservative starting values not yet tuned on real
  multi-person footage; height-based distance assumes 1.7m (a child or a very
  tall person skews it) and the calibration intrinsics are still placeholders;
  Follow's backward retreat is toward a side the camera cannot see, which
  this audit did not change.
- **Tests**: `test_guidance_limits.py`, `test_motion_model.py`,
  `test_distance_accuracy.py`, `test_identity_check.py`,
  `test_tracking_safety_orchestrator.py` (real-pixel swap/drop/no-false-trigger
  and REACQUIRE-hold, mutation-checked), plus health-check and grid-search
  clamp tests.

## Deep audit: flight-controller data, operator link, failsafes

Second full audit, focused on "does the FC get correct commands and does the
drone stay stable and safe through a mission".

- **Verified correct against the MAVLink/ArduCopter spec (no change needed)**:
  `SET_POSITION_TARGET_LOCAL_NED` type mask 1479 (velocity + yaw rate, position/
  acceleration/yaw ignored); `MAV_FRAME_BODY_OFFSET_NED` (ArduCopter rotates
  body-frame velocity by current yaw); +x forward, +y right, +z DOWN (Follow's
  climb is negative vz); yaw rate positive = clockwise (target right of center
  yaws right); `GLOBAL_POSITION_INT` lat/lon /1e7 and `relative_alt` mm to m;
  grid-search bearing/heading-error sign. Still **not** confirmed against a
  real flying FC.
- **Operator-link loss was detected only by socket state** - a dropped WiFi
  link leaves a TCP socket "connected" for tens of seconds (the WebSocket
  library's own keepalive is 20 s + 20 s), the app sent no traffic, and the
  documented 1.5 s comms timeout was never used anywhere. So "phone link lost
  stops guidance" was not true in practice. Now: the app pings every 500 ms,
  the Pi treats `comms_timeout_s` (3 s) without any message as link loss
  (`comms_lost`), and OkHttp pings the Pi every 2 s so the app notices a dead
  Pi link in seconds too.
- **Nothing brought a stranded drone home.** After comms loss the Pi only
  stopped its setpoints, leaving the aircraft hovering in GUIDED until the
  battery died (ArduPilot's GCS failsafe does not count a companion computer's
  heartbeat). The Pi now requests RTL once per episode after `comms_loss_rtl_s`
  (15 s) of continuous loss, or at critical battery (`min_battery_pct`), only
  while it is the one holding the aircraft (armed + GUIDED), never while the
  pilot has RC override, and never re-fired after the pilot changes mode.
- **Geofence and battery only mattered to Approach-Test.** Both now stop ALL
  guidance in the Supervisor (`geofence_breached`, `battery_critical`);
  Approach-Test is excluded from the fence gate so it keeps its own sticky
  abort. The FC's own fence/battery failsafes remain the primary protection.
- **Frozen telemetry.** The bridge requested telemetry streams once and never
  again: after an FC reboot (heartbeats resume, stream rates reset) altitude and
  GPS would freeze at their last values while everything looked alive. It now
  re-requests when position data goes stale, rate-limited, and guidance reads
  `fresh_alt_m()`/`fresh_position()` - older than 2 s counts as unknown.
  **Unknown altitude now holds all vertical motion** (previously it only
  blocked descent), because neither floor nor ceiling can be verified.
- **GPS-navigated grid search** refuses to start, and holds if it loses, a 3D
  fix with acceptable HDOP (unknown counts as bad), and never steers on a stale
  position. Its forward speed ramps and its vertical command obeys the same
  floor/ceiling as Follow/Orbit.
- **Arm & Follow pre-takeoff checks**: refused (and shown to the operator) on a
  reported bad GPS fix or low battery; values the FC has not reported yet are
  not treated as failures (the FC refuses a takeoff without a position itself).
- **Force disarm** is refused above `max_force_disarm_altitude_m` (1.5 m) when
  altitude is known: forced disarm cuts the motors and would drop a flying
  aircraft; the app's confirmation dialog is no longer the only guard.
- **Stalled frame loop**: a frame gap over 0.5 s no longer feeds a huge dt to
  the PID derivative/acceleration limiter; controllers restart from standstill.
- **Blind retreat capped**: Follow/Orbit backing away is limited to
  `max_reverse_speed_mps` (1 m/s) - the camera faces forward.
- **Detector**: non-finite or degenerate boxes from the on-sensor model are
  dropped before they reach tracking/distance/appearance math.
- **Boot check** now also refuses to start on a camera resolution that does not
  match the calibration (distances would be silently wrong) and on any missing
  failsafe setting.
- **Explicitly NOT covered - be aware**: (1) **obstacle avoidance is vision-only
  and class-based** - it recognises COCO objects (people, cars...), not walls,
  trees, poles, wires or glass; do not fly Follow near unmapped obstacles
  without a rangefinder or FC-side avoidance. (2) **FC parameters are outside
  this code and unverified**: confirm on the real FC `BATT_LOW_ACT`/
  `BATT_CRT_ACT`, `FENCE_ENABLE`/`FENCE_ACTION`, `GUID_TIMEOUT`, `RTL_ALT`, GPS
  and EKF failsafes, `FLTMODE_CH`. (3) A frozen Pi process or dead camera stops
  setpoints, after which the FC's own GUIDED velocity timeout holds position
  (it does not land). (4) Calibration intrinsics are still placeholders. (5) No
  SITL or flight test of any of this has been run.
- **Tests**: `test_failsafes_and_freshness.py` (link liveness, stream
  re-request, telemetry freshness, supervisor gates, failsafe RTL incl. latch/
  RC-override/not-guided cases, takeoff refusal, grid GPS gating, stalled loop,
  reverse cap, detector, force-disarm guard) - mutation-checked - plus updates
  to the health-check tests.

## Teach mode (taught objects) - what is and is not protected

A field request: "detect and learn new things". The on-sensor model is fixed, so this
adds (1) tracking of an operator-drawn object with a class-agnostic OpenCV tracker and
(2) capture of labelled photos for **offline** training. It never changes flight
behaviour or safety limits by itself.

- **The new risk**: a taught object is tracked by pixels alone - no detector confirms it
  is still on the object, so the tracker can drift onto background. Mitigations:
  the appearance identity check runs on every tracked frame (drift becomes a hold, then
  target-lost, exactly as for a swapped person - tested with real pixels); sanity limits
  on box size/shape/position reject implausible tracker output; Follow/Orbit speed is
  capped at 1.5 m/s while the target is a taught object; **no automatic re-lock** (a lost
  object must be re-drawn by the operator).
- **No guessed distance**: without a real size a taught object has no distance estimate,
  and Follow holds its forward speed at zero. Implausible sizes are ignored.
- **Not an obstacle**: taught objects are not detections, so the obstacle-proximity check
  cannot see them. This is deliberate and documented; it changes only when a retrained
  model detects them (then their real size applies).
- **Control loop protected**: the tracker costs tens of milliseconds a frame (measured,
  laptop CPU) so it runs on a worker thread; it cannot stall link heartbeats, the
  watchdog or MAVLink handling. The Pi's cost is not yet measured - lab checklist 6D.
- **Untrusted input**: every `teach_object` field comes from the app. The name is reduced
  to a `[a-z0-9_-]` slug (no path can be formed - tested with `../../..`), the box must be
  finite and positive, sizes are range-checked, the registry (100 objects) and dataset
  (400 photos/object, 500 MB total) are capped, and registry writes are atomic.
- **Dataset quality gates**: photos are saved only while the track still matches the
  object, not for near-duplicates, and never for a box clipped by the frame edge; each
  photo is labelled against the exact frame the tracker processed. JPEG encoding is on a
  background thread.
- **Deploying a retrained model is a separate, deliberate step** (`docs/teach-and-train.md`):
  labels file, `bbox_order` (a swapped x/y order looks plausible but is wrong), and the
  lab stages must be re-run. A model trained only on taught objects forgets people/cars,
  which this system depends on - the guide says to merge datasets.
- **Not verified**: training, IMX500 conversion and on-sensor deployment of a retrained
  model were **not run** here (documented from vendor docs); tracker drift and speed on
  real footage/the Pi are untested.
- **Tests**: `test_teach_mode.py` (real OpenCV tracking on synthetic moving video, dataset
  gates and label correctness, registry safety, distance for taught sizes, the full
  orchestrator flow incl. drift/loss/abort/selection, speed cap, off-loop execution) and
  `test_export_taught_dataset.py` - mutation-checked.

## Flight-mode requests are confirmed, retried and reported

- **Gap**: every mode change the Pi asks for (GUIDED for a guidance mode, LOITER on stick
  override, RTL on failsafe, BRAKE on STOP) was sent once with no confirmation. A request
  lost on the serial link was never noticed - and for the failsafe RTL the once-per-episode
  latch turned one lost message into a permanent failure: a drone with no operator link
  or a dying battery would keep hovering in GUIDED.
- **Mechanism**: `MavlinkBridge.set_mode()` records the request; `check_pending_mode()`
  (once per frame) resolves it against the FC's HEARTBEAT. Confirmed when the reported
  mode matches; re-sent after 1.5 s if the mode is unchanged, up to 3 sends in total;
  then reported as not confirmed (`mode_change_result`, session log, spoken alert in
  the app).
- **Never fights the pilot**: if the mode changed to something *else* while waiting (the
  pilot's switch), the request is dropped silently - no re-send, no failure. No re-send
  while the pilot has RC stick override either.
- **Limits**: confirmation is by the mode the FC reports, which is only as fresh as its
  1 Hz heartbeat, hence the 1.5 s retry delay. A mode the FC refuses on purpose (e.g. BRAKE
  or GUIDED without a position estimate) also ends as "not confirmed" - that is the
  intended signal, not a fault. Not confirmed against a real FC.
- **Tests**: `test_mode_confirmation.py` (confirm, delayed retry, attempt cap, late
  confirmation, pilot-changed-mode, RC override, replacement, unknown mode, and the
  failsafe-RTL retry / never-happens / stick-override cases through the orchestrator) -
  mutation-checked.

## Grid Search finishing - a deliberately different design from Approach-Test

- Unlike the above, a Grid Search sweep that finishes on its own (every
  waypoint visited) has no residual safety significance, so
  `companion/main.py` resets `requested_mode` to `IDLE` the moment
  `GridSearchController.phase` reports `FINISHED`, and the Android app
  mirrors this by reverting its own mode selector - see
  `test_grid_search_orchestrator.py::test_grid_search_finishing_drops_back_to_idle`.
  This is called out here specifically so it isn't mistaken for an
  inconsistency with Approach-Test's deliberately-sticky behavior above -
  it's a considered difference, not an oversight.

## Safety pass: detection flicker, link and process recovery

- **Detection flicker**: the IMX500 does not attach an AI result to every
  camera frame. Those frames used to parse as "no detections", so the
  tracker counted a miss, the target flipped TRACKING -> REACQUIRE, Follow
  commanded a zero-velocity hold for that frame (the drone stuttered) and the
  app's boxes blinked. `IMX500Detector.parse()` now returns `None` for "no
  result" (distinct from `[]`, "the model saw nothing"). The orchestrator
  reuses the last real detections for up to `detection_carry_max_s` (0.5 s) -
  for the app's boxes, tap-to-select and the obstacle check - and skips the
  tracker update on those frames (`TrackingStateMachine.coast()`), along with
  the identity check and appearance re-match, which compare boxes against
  the current image. Follow/Orbit hold only once the target has been unseen
  for `target_hold_after_unseen_s` (0.3 s), measured from the target's
  last sighting - so a TRACKING target whose results have stopped arriving
  is held too, and after `detection_carry_max_s` a stopped AI degrades to
  "saw nothing" and on to TARGET_LOST. A target judged to be the wrong person
  is still held immediately.
- **MAVLink reconnect**: a read error, a failed write, or no MAVLink data
  for `mavlink.silence_reconnect_s` (5 s) closes the connection and reopens
  it, backing off up to `reconnect_max_delay_s` while the port will not open,
  and never giving up. The FC's telemetry streams are requested again on the
  new link's first heartbeat. Previously a read error ended the receive task
  silently (telemetry froze until a service restart) and a write error
  either skipped a whole perception frame or killed the companion's own
  heartbeat task for good. Writes now report failure instead: a velocity
  setpoint shows `guidance_sent: false`, an unsendable arm request is
  reported rejected, a mode request is retried like a lost packet.
  Guidance has already stopped (2 s watchdog) before a silent link is reopened.
- **Slow ground-station client**: `WebSocketTransport.broadcast()` used to
  await every client's send, which waits for the socket to drain - one phone
  on weak WiFi stalled the perception loop and with it every setpoint,
  telemetry update and failsafe check. Each client now has its own queue
  and writer task. A client `ws_send_queue_max` (200) messages behind (about
  a second of updates) is closed with code 1013 and no longer counts as
  connected (so guidance pauses, exactly as for a lost link); the app
  reconnects fresh.
- **Parameters**: all of the above are in config (`safety_limits.yaml`,
  `hardware.yaml`, `network.yaml`), required by the startup health check and
  range-checked there - e.g. `target_hold_after_unseen_s` above 1 s refuses
  to boot, so a typo cannot quietly bring back steering on stale boxes. The
  check also refuses a camera stall timeout that is not shorter than the
  pipeline frame age.
- **Tests**: `test_tracking_safety_orchestrator.py` (flicker/carry/hold),
  `test_state_machine.py` (coast), `test_imx500_detector.py`,
  `test_mavlink_reconnect.py`, `test_transport_slow_client.py`,
  `test_camera_stall.py`, `test_service_watchdog.py`,
  `test_safety_parameters.py`.
- **Not yet verified on hardware**: all of it - see the lab checklist rows
  6A.5, 5.8-5.10, 7C.3, 7C.5, 9.12 and 10.7-10.8.

## Fault-injection test coverage summary

Every mechanism above that has a corresponding `SafetySupervisor` gate is
covered by at least one test that independently trips *only that
condition* and asserts guidance is denied - this is what "fault injection"
means in this codebase's test suite, not a separate framework. As of this
writing: 763 companion tests passing
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
- **Two known gaps found in a code-review audit, now both fixed**
  (beyond the RC_CHANNELS-staleness one under "RC override" above):
  - `SessionRecorder.record()` (`companion/logging_/session_recorder.py`)
    used to do a synchronous file write + flush on every call, from inside
    the async per-frame hot loop, with no executor offload. Several calls
    can fire within a single frame (an obstacle alert, a guidance command,
    etc.), and on Pi SD/eMMC storage under contention (e.g. concurrent
    video recording) each flush is a blocking syscall that can stall
    MAVLink receive and WebRTC delivery for its duration. **Fixed**: the
    write+flush is now offloaded to a single-worker thread pool owned by
    the recorder itself - `record()` returns immediately from every call
    site (both the async hot loop and the several plain-sync handler
    callbacks that also call it), while the single worker preserves append
    order. `close()` drains the pool before closing the file, so a normal
    shutdown never drops a pending write; the only remaining durability
    trade-off is the (very small) window between a submit and that worker
    thread actually running it. Unit-tested (`test_session_recorder.py::
    test_record_offloads_writes_without_losing_order_or_entries`).
  - `DistanceEstimator.estimate()` (`companion/guidance/distance.py`) used
    to return a single rangefinder reading for every detection in the
    frame it's asked about, not specifically the tracked target's own
    distance - unreachable in practice at the time (`RangefinderSource.
    __init__` always raises `NotImplementedError`, since the M4
    rangefinder still hasn't been purchased - see root README), but once
    real rangefinder hardware is wired up this would have made
    `check_proximity()` report the tracked target's distance for every
    object in frame, including untracked obstacles at a genuinely
    different distance, silently defeating the obstacle-proximity check
    for anything not being tracked. **Fixed ahead of the hardware
    decision**, per the product decision flagged here previously (only
    trust the rangefinder for the actively tracked target, fall back to
    vision-only for everything else): `estimate()` now takes an explicit
    `trust_rangefinder` flag, defaulting to `False`; `check_proximity()`
    matches each candidate detection against the tracker's current target
    by class + IoU and only sets it `True` for that match. Unit-tested
    (`test_distance.py::test_estimator_ignores_rangefinder_by_default_even_when_available`,
    `test_proximity_guard.py::test_only_the_matching_detection_trusts_the_rangefinder_not_the_rest`).
