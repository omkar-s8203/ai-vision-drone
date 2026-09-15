from companion.safety.watchdog import HeartbeatWatchdog


def test_unbeaten_subsystem_is_stale():
    wd = HeartbeatWatchdog(timeout_s=1.0)
    assert wd.is_stale("camera") is True


def test_freshly_beaten_subsystem_is_not_stale():
    clock = [0.0]
    wd = HeartbeatWatchdog(timeout_s=1.0, clock=lambda: clock[0])
    wd.beat("camera")
    assert wd.is_stale("camera") is False


def test_subsystem_becomes_stale_after_timeout():
    clock = [0.0]
    wd = HeartbeatWatchdog(timeout_s=1.0, clock=lambda: clock[0])
    wd.beat("camera")
    clock[0] = 1.5
    assert wd.is_stale("camera") is True


def test_stale_subsystems_lists_only_stale_ones():
    clock = [0.0]
    wd = HeartbeatWatchdog(timeout_s=1.0, clock=lambda: clock[0])
    wd.beat("camera")
    assert wd.stale_subsystems(["camera", "tracker"]) == ["tracker"]
