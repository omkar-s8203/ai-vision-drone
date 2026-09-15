from companion.mavlink.rc_monitor import RcOverrideMonitor


def test_centered_sticks_not_overriding():
    monitor = RcOverrideMonitor(deadband=0.15)
    assert monitor.is_overriding({1: 1500, 2: 1500, 3: 1500, 4: 1500}) is False


def test_deflected_stick_beyond_deadband_is_overriding():
    monitor = RcOverrideMonitor(deadband=0.15)
    assert monitor.is_overriding({1: 1900, 2: 1500, 3: 1500, 4: 1500}) is True


def test_small_deflection_within_deadband_is_not_overriding():
    monitor = RcOverrideMonitor(deadband=0.15)
    # (1550-1500)/500 = 0.1, below 0.15 deadband
    assert monitor.is_overriding({1: 1550, 2: 1500, 3: 1500, 4: 1500}) is False


def test_missing_channels_are_ignored():
    monitor = RcOverrideMonitor(deadband=0.15)
    assert monitor.is_overriding({}) is False
