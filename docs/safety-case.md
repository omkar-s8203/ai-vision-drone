# Safety Case

Status: not yet written — this will be filled in during M7 (MAVLink/RC Override) and M10 (Safety Architecture & Watchdog).

This document will explicitly record, for each safety-relevant behavior:
- The mechanism (e.g. RC override via `FLTMODE_CH`, hardware path independent of the Pi).
- What triggers it.
- What guarantees it does and does not provide.
- The test (SITL, bench, or real-flight) that verifies it, and its pass record.

Required entries (see the project plan): RC override, target-loss handling, comms-loss handling, MAVLink-failure handling, camera-failure handling, geofence, watchdog/fault-injection results.
