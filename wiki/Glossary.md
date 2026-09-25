# Glossary

| Term | Meaning |
|---|---|
| **AI Camera / IMX500** | Raspberry Pi camera module whose Sony IMX500 sensor runs a neural network on the chip |
| **ArduPilot / ArduCopter** | The open-source flight-control firmware on the flight controller |
| **Abort / STOP** | The app's stop button: ends all guidance and commands BRAKE |
| **Approach-Test** | A tightly bounded, slow approach to a test fixture; for controlled experiments only |
| **Appearance signature** | A colour histogram of the target, used for identity checks and re-locking |
| **Arm & Follow** | One-tap arm, climb to 10 m, then Follow |
| **BRAKE** | ArduCopter mode that stops and holds the current position |
| **Carry-over** | Reusing the last real AI detections on frames that carry no AI result (≤ 0.5 s) |
| **Coast** | Advancing the tracking state on a frame with no AI result without updating the tracker |
| **Companion computer** | The Raspberry Pi: advises the flight controller, never replaces it |
| **Cube Orange** | The CubePilot flight controller used in this build |
| **Detection** | One object the AI found: box, class, score |
| **FC** | Flight controller |
| **`FLTMODE_CH`** | ArduPilot parameter naming the RC channel that selects flight mode - the hardware override |
| **`GUID_TIMEOUT`** | ArduCopter's timeout after which it stops obeying old GUIDED velocity setpoints and holds |
| **GUIDED** | ArduCopter mode that accepts external commands; the only mode in which the Pi guides |
| **Grid Search** | Lawnmower sweep of an area along GPS waypoints |
| **`guidance_bbox`** | The motion-filtered target box used for guidance (the raw box is for display) |
| **`guidance_hold`** | Why guidance is deliberately holding still although allowed |
| **`guidance_reason`** | Why the Supervisor refused guidance |
| **HDOP** | GPS horizontal dilution of precision; lower is better (≤ 2.5 required) |
| **Health check (startup)** | Boot-time validation of every config file before any hardware is touched |
| **Hold** | A zero-velocity command |
| **IoU** | Intersection over union - the overlap between two boxes |
| **LOITER** | ArduCopter position-hold mode that responds to the sticks; requested on stick override |
| **MAVLink** | The message protocol between the Pi and the flight controller |
| **Mock FC** | `sim/mock_fc.py`, a lightweight MAVLink stand-in for tests and sim mode |
| **NED** | North-East-Down frame; in body frame +x forward, +y right, **+z down** |
| **Orbit** | Circling the target at a set radius |
| **REACQUIRE** | Tracking state: target briefly unseen, last box kept |
| **RC override** | The pilot taking control: the hardware mode switch (guaranteed) or stick deflection (software backstop) |
| **RTL** | Return To Launch |
| **SAFE** | Supervisor state: guidance disabled |
| **Safety Supervisor** | The single gate deciding whether a guidance command may reach the FC |
| **sd_notify** | The systemd protocol used for READY and WATCHDOG notifications |
| **Session log** | Per-run JSONL timeline of events on the Pi |
| **Setpoint** | A velocity command sent to the FC |
| **SITL** | Software In The Loop - real ArduPilot running on a computer |
| **Stale subsystem** | A required part (camera, tracker, MAVLink, link, RC channels) silent for > 2 s |
| **TARGET_LOST** | Tracking state: gone for 2 s since last sighting |
| **Teach mode** | Tracking an object the AI has no class for, while collecting training photos |
| **TEMP EDIT** | A deliberate temporary config change during lab tests - always reverted |
| **TELEM1** | The flight controller's telemetry serial port wired to the Pi |
| **Watchdog (subsystem)** | `HeartbeatWatchdog`: per-subsystem freshness feeding the Supervisor |
| **Watchdog (service)** | systemd's `WatchdogSec`: kills and restarts a hung companion |
