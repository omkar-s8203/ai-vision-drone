# Flight-Readiness Checklist

Status: living checklist - tracks the two concrete next steps toward real
flight, in order. Neither can be done by editing code; both require hands
on the physical transmitter/aircraft. See `docs/safety-case.md` for why
each of these matters and `README.md`'s "What's next" for how this fits
into the bigger picture.

**Superseded for bench testing by [`lab-test-checklist.md`](lab-test-checklist.md)**
(the complete props-off protocol, including the operator-link, battery, GPS and
force-disarm failsafes added later). The two steps below remain accurate and are
repeated there as Stage 4 and Stage 7.

**Do not skip ahead.** Step 2 assumes step 1 is already confirmed working
- running a guidance dry-run before the hardware override is proven would
defeat the entire point of the override.

## Step 1: Configure and verify `FLTMODE_CH`

This is the actual, non-negotiable safety guarantee the whole project is
built around - a hardware switch on the transmitter that changes the
flight controller's mode through the RC receiver directly, a path that
physically never touches the Pi. Software (`RcOverrideMonitor`) is only
ever a backstop on top of this, not a substitute for it.

### 1a. Assign a transmitter switch

Pick an unused 2- or 3-position switch on the transmitter and assign it to
an auxiliary channel your receiver isn't already using for something else
(commonly channel 5, but depends on your radio/receiver setup - check
your transmitter's channel-mapping/mixing menu, since this varies by
brand). Note which channel number you used - you'll need it in the next
step.

### 1b. Set the FC parameters (Mission Planner / QGroundControl, connected via USB)

- `FLTMODE_CH` = the channel number from 1a.
- `FLTMODE1` through `FLTMODE6` (one per switch position/range) - set at
  least one position to `GUIDED` (this codebase's
  `AI_GUIDANCE_MODE_NAME` in `companion/main.py` - AI guidance only ever
  activates while the FC reports this exact mode) and at least one
  position to a safe manual mode (`STABILIZE` or `LOITER` are the usual
  choices). `ARDUCOPTER_MODE_TO_NUMBER` in
  `companion/mavlink/bridge.py` lists every mode name this project's code
  already recognizes if you want the Android app's own mode dropdown to
  match.

### 1c. Verify with the Pi powered off (or disconnected)

This is the step that actually proves the guarantee - if this works with
the Pi off, it's real; if you only ever test it with the Pi on, you
haven't proven anything about what happens when the Pi isn't there to
help.

- [ ] Power the aircraft's flight-control system with the Pi off or
      physically disconnected.
- [ ] Cycle the transmitter switch through every position.
- [ ] Confirm on Mission Planner/QGroundControl's HUD that the FC's
      reported flight mode changes correctly for every position, with no
      Pi involved at all.

### 1d. Verify override while the Pi is actively "guiding" (props still off)

- [ ] Power the Pi and run `companion.main` in hardware mode, FC
      connected, as usual.
- [ ] Get the FC into `GUIDED` via the transmitter switch. (The Pi will
      also now request `GUIDED` on its own the moment a guidance mode is
      selected in the app - see `docs/safety-case.md`'s "the Pi
      automatically requests GUIDED" entry - but doing it manually here
      first is the more conservative way to test this specific override
      direction: it isolates "does the switch's forward direction work"
      from "did the app's own request happen to work.")
- [ ] Select a target and switch to Follow (or Orbit) in the Android app -
      confirm the `GuidanceCommandPanel` shows `GUIDANCE SENT` with real
      vx/vy/vz/yaw numbers ticking (this is the same dashboard from the
      recent `tracking_update` addition - see `docs/protocol.md`).
- [ ] With guidance actively "sending" (props still off - nothing should
      be spinning at this stage regardless of switch position), flip the
      transmitter switch away from `GUIDED`.
- [ ] Confirm: the FC's reported mode changes immediately, and
      `GuidanceCommandPanel` reports `GUIDANCE BLOCKED` (the Pi's own
      `fc_not_in_ai_mode` gate should trip in `SafetySupervisor`, visible
      via `GuidanceWarningBanner`) essentially at the same moment.
- [ ] **Repeat 20/20 times, matching this project's plan (M7) acceptance
      criteria: "flipping the transmitter mode switch immediately and
      reliably returns manual control, 20/20 trials."** Fewer than 20/20
      is a blocking failure, not a tunable - if it doesn't work every
      single time, do not proceed to step 2 or to real flight until it
      does.

Once both 1c and 1d pass, update `docs/safety-case.md`'s RC-override
section and README's "What's next" to record it - this is exactly the
kind of real-hardware confirmation this project tracks explicitly rather
than assuming.

## Step 2: Props-off guidance dry-run

Only after step 1 is fully confirmed. This is the first time any guidance
controller (Follow/Orbit/Approach-Test) will have ever computed and sent
a real velocity setpoint to the real flight controller - previously only
proven against a mock FC in tests.

- [ ] Props physically removed or the aircraft otherwise restrained -
      nothing should be able to move even if something goes wrong.
- [ ] Run `companion.main` in hardware mode, FC connected, aircraft
      mounted (as already confirmed working - M14 stage 1).
- [ ] Get the FC into `GUIDED`, select a target, switch to Follow.
- [ ] Watch `GuidanceCommandPanel` on the Android app: confirm the
      commanded vx/vy/vz/yaw values are sane for the target's actual
      position/motion (e.g. vx should trend positive if the target is
      farther than the configured separation, roughly zero once framed
      correctly) - this is exactly the "watch commanded velocities on a
      dashboard before ever arming" step the plan's own M14 calls for.
- [ ] Repeat for Orbit.
- [ ] Deliberately move the target out of frame long enough to trigger
      `TARGET_LOST`, and confirm the new target-loss recovery search
      engages: `GuidanceCommandPanel` should show `SEARCHING FOR TARGET`
      with a yaw-only command (vx/vy/vz all zero). Bring the target back
      into view and confirm the search cancels and Follow resumes.
  - Optionally, to test the RTL/land decision path without waiting a full
    60s: temporarily lower `search_timeout_s` in
    `companion/config/target_recovery.yaml` on the bench (revert
    afterward), keep the target out of view, and confirm either `RTL`
    gets set on the FC (healthy battery) or a `land_confirmation_request`
    reaches the Android app (artificially drop `battery_remaining_pct` via
    the mock FC path, or test this specific piece in sim instead of on
    real hardware if there's no safe way to fake low battery on the real
    FC).
- [ ] Re-run the step 1d override test *while Follow is actively engaged
      with a real target* (not just a "pretend" state) - confirm the
      switch still interrupts it immediately, 20/20.

Once this passes, update README's "What's next" (items 3 and 9) and
`docs/safety-case.md` accordingly, and move on to the plan's next staged
step (M14 stage 2: tethered/ground hover, Normal RC, Pi passive) - not
straight to a guided flight.
