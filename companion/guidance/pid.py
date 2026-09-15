from __future__ import annotations


class Pid:
    def __init__(self, kp: float, ki: float, kd: float, out_limit: float | None = None) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_limit = out_limit
        self._integral = 0.0
        self._prev_error: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = None

    def step(self, error: float, dt: float) -> float:
        if dt <= 0:
            return 0.0
        self._integral += error * dt
        derivative = 0.0 if self._prev_error is None else (error - self._prev_error) / dt
        self._prev_error = error
        output = self.kp * error + self.ki * self._integral + self.kd * derivative
        if self.out_limit is not None:
            output = max(-self.out_limit, min(self.out_limit, output))
        return output
