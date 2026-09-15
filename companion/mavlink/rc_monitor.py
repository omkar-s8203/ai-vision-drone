from __future__ import annotations


class RcOverrideMonitor:
    """Secondary software backstop for RC override detection. The primary,
    guaranteed mechanism is the pilot's hardware flight-mode switch, which
    changes the FC's mode directly through the RC receiver and never passes
    through the Pi (docs plan M7 / docs/safety-case.md). This monitor only
    adds an extra layer: stick deflection beyond a deadband while AI
    guidance is active is treated as override intent.
    """

    MONITORED_CHANNELS = (1, 2, 3, 4)  # roll, pitch, throttle, yaw

    def __init__(
        self, deadband: float = 0.15, channel_center: int = 1500, channel_range: int = 500
    ) -> None:
        self.deadband = deadband
        self.channel_center = channel_center
        self.channel_range = channel_range

    def is_overriding(self, rc_channels: dict[int, int]) -> bool:
        for ch in self.MONITORED_CHANNELS:
            value = rc_channels.get(ch)
            if value is None:
                continue
            normalized = (value - self.channel_center) / self.channel_range
            if abs(normalized) > self.deadband:
                return True
        return False
