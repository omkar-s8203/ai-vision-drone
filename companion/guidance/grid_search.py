from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from companion.guidance.command import GuidanceCommand
from companion.guidance.geo import bearing_deg, generate_lawnmower_waypoints, haversine_distance_m
from companion.guidance.pid import Pid


class GridSearchPhase(Enum):
    IDLE = auto()  # not engaged
    SEARCHING = auto()  # actively flying the planned sweep
    FINISHED = auto()  # every waypoint visited


@dataclass
class GridSearchStatus:
    """Surfaced to the operator (Android's live map + AI Modes tab) so the
    planned route and progress are visible, not just a bare "active" flag."""

    phase: GridSearchPhase
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    current_index: int = 0


class GridSearchController:
    """Systematic area-sweep ("lawnmower"/boustrophedon) guidance mode - a
    field request extending the existing single-target yaw-sweep search
    (companion/guidance/target_recovery.py, which searches in place for a
    lost target) into deliberate area coverage instead - the same recon/
    surveillance use case as the perimeter/intrusion alert (Android side).

    Unlike Follow/Orbit, which react every frame to a visually tracked
    target, this flies a pre-planned route of absolute GPS waypoints laid
    out once at `start()` (see generate_lawnmower_waypoints). It still
    never touches MAVLink directly - only returns a GuidanceCommand for the
    Safety Supervisor to gate, exactly like every other controller in this
    project (companion/main.py is the sole caller of
    MavlinkBridge.send_velocity_setpoint()).

    Waypoint-following works in the same MAV_FRAME_BODY_OFFSET_NED frame
    send_velocity_setpoint() already sends in: at each step, the bearing
    from the aircraft's current position to the next waypoint is compared
    against its current compass heading to get a body-relative heading
    error, which a yaw-rate PID steers toward zero. Forward speed only
    engages once roughly facing the waypoint
    (`max_heading_error_deg_to_advance`) - moving forward at speed while
    still turning to face the right way would send the aircraft off in the
    wrong direction rather than toward the next point.
    """

    def __init__(self, limits: dict) -> None:
        self.limits = limits
        pid_cfg = limits["pid"]
        self._yaw_pid = Pid(**pid_cfg["yaw"], out_limit=limits["max_yaw_rate_rads"])
        self._altitude_pid = Pid(**pid_cfg["altitude"], out_limit=limits["max_speed_mps"])
        self._waypoints: list[tuple[float, float]] = []
        self._current_index = 0
        self.phase = GridSearchPhase.IDLE

    @property
    def is_active(self) -> bool:
        return self.phase == GridSearchPhase.SEARCHING

    def start(
        self,
        start_lat: float,
        start_lon: float,
        width_m: float,
        height_m: float,
        heading_deg: float = 0.0,
    ) -> None:
        """(Re)plans the sweep area from a single starting corner - the
        aircraft's own current position at the moment the operator engages
        this mode (see main.py's mode_command handling), rather than
        requiring an interactive map-drawing UI: fly to one corner of the
        area to be searched, then start the sweep from there."""
        self._waypoints = generate_lawnmower_waypoints(
            start_lat, start_lon, width_m, height_m, self.limits["leg_spacing_m"], heading_deg
        )
        self._current_index = 0
        self.phase = GridSearchPhase.SEARCHING
        self._yaw_pid.reset()
        self._altitude_pid.reset()

    def reset(self) -> None:
        self._waypoints = []
        self._current_index = 0
        self.phase = GridSearchPhase.IDLE
        self._yaw_pid.reset()
        self._altitude_pid.reset()

    def status(self) -> GridSearchStatus:
        return GridSearchStatus(phase=self.phase, waypoints=list(self._waypoints), current_index=self._current_index)

    def compute(
        self,
        current_lat: Optional[float],
        current_lon: Optional[float],
        current_heading_deg: Optional[float],
        current_altitude_m: Optional[float],
        dt: float,
    ) -> Optional[GuidanceCommand]:
        """Returns None (not a zero-velocity command) when there's nothing
        useful to compute - missing GPS/heading telemetry, or the sweep
        already finished - so the caller can tell "no command" apart from
        "hold still," the same way ApproachTestController signals
        completion through its own state rather than a fabricated
        command."""
        if self.phase != GridSearchPhase.SEARCHING:
            return None
        if current_lat is None or current_lon is None or current_heading_deg is None:
            return None
        if self._current_index >= len(self._waypoints):
            self.phase = GridSearchPhase.FINISHED
            return None

        target_lat, target_lon = self._waypoints[self._current_index]
        distance = haversine_distance_m(current_lat, current_lon, target_lat, target_lon)
        if distance < self.limits["waypoint_radius_m"]:
            self._current_index += 1
            if self._current_index >= len(self._waypoints):
                self.phase = GridSearchPhase.FINISHED
                return None
            target_lat, target_lon = self._waypoints[self._current_index]

        bearing = bearing_deg(current_lat, current_lon, target_lat, target_lon)
        heading_error_deg = ((bearing - current_heading_deg + 180.0) % 360.0) - 180.0
        yaw_rate = self._yaw_pid.step(heading_error_deg, dt)

        facing_waypoint = abs(heading_error_deg) < self.limits["max_heading_error_deg_to_advance"]
        vx = self.limits["search_speed_mps"] if facing_waypoint else 0.0

        max_speed = self.limits["max_speed_mps"]
        vz = 0.0
        target_altitude_m = self.limits.get("search_altitude_m")
        if target_altitude_m is not None and current_altitude_m is not None:
            altitude_error = target_altitude_m - current_altitude_m
            vz = -self._altitude_pid.step(altitude_error, dt)  # NED: negative = up
            vz = max(-max_speed, min(max_speed, vz))

        return GuidanceCommand(vx_mps=vx, vy_mps=0.0, vz_mps=vz, yaw_rate_rads=yaw_rate)
