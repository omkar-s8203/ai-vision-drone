from companion.config.loader import load_yaml
from companion.guidance.geo import bearing_deg, haversine_distance_m
from companion.guidance.grid_search import GridSearchController, GridSearchPhase

LIMITS = load_yaml("grid_search_limits.yaml")


def make_controller(**overrides) -> GridSearchController:
    limits = dict(LIMITS)
    limits.update(overrides)
    return GridSearchController(limits)


def test_idle_before_start():
    controller = make_controller()
    assert controller.phase == GridSearchPhase.IDLE
    assert controller.is_active is False
    assert controller.compute(0.0, 0.0, 0.0, None, 0.1) is None


def test_start_lays_out_waypoints_and_enters_searching():
    controller = make_controller()
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0, heading_deg=0.0)
    assert controller.phase == GridSearchPhase.SEARCHING
    assert controller.is_active is True
    status = controller.status()
    assert len(status.waypoints) >= 2
    assert status.current_index == 0


def test_compute_yaws_toward_the_first_waypoint_when_not_facing_it():
    controller = make_controller(max_heading_error_deg_to_advance=5.0)
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0, heading_deg=0.0)
    # First leg heads east (bearing ~90); starting the aircraft facing
    # north (heading 0) means a large heading error, so it should steer
    # (nonzero yaw_rate) without yet moving forward.
    command = controller.compute(current_lat=0.0, current_lon=0.0, current_heading_deg=0.0, current_altitude_m=None, dt=0.1)
    assert command is not None
    assert command.yaw_rate_rads != 0.0
    assert command.vx_mps == 0.0  # not facing the waypoint yet


def test_compute_moves_forward_once_facing_the_waypoint():
    controller = make_controller(max_heading_error_deg_to_advance=5.0)
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0, heading_deg=0.0)
    # The starting position is itself waypoint 0 (generate_lawnmower_
    # waypoints anchors the first point exactly at the given start), so
    # the very first compute() call immediately advances past it (0m away,
    # well under waypoint_radius_m) to waypoint 1 before doing anything
    # else - this targets that real waypoint, not the degenerate one.
    waypoint_1 = controller.status().waypoints[1]
    bearing_to_next = bearing_deg(0.0, 0.0, *waypoint_1)
    command = controller.compute(
        current_lat=0.0, current_lon=0.0, current_heading_deg=bearing_to_next, current_altitude_m=None, dt=0.1
    )
    assert command is not None
    assert command.vx_mps > 0.0
    assert controller.status().current_index == 1


def test_reaching_a_waypoint_advances_to_the_next_one():
    controller = make_controller(waypoint_radius_m=3.0)
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0, heading_deg=0.0)
    first_waypoint = controller.status().waypoints[0]
    # Drive the "current position" essentially onto the first waypoint.
    controller.compute(
        current_lat=first_waypoint[0], current_lon=first_waypoint[1],
        current_heading_deg=0.0, current_altitude_m=None, dt=0.1,
    )
    assert controller.status().current_index == 1


def test_finishes_once_every_waypoint_is_reached():
    controller = make_controller(waypoint_radius_m=3.0)
    controller.start(0.0, 0.0, width_m=20.0, height_m=5.0, heading_deg=0.0)
    waypoints = controller.status().waypoints
    for lat, lon in waypoints:
        controller.compute(current_lat=lat, current_lon=lon, current_heading_deg=0.0, current_altitude_m=None, dt=0.1)
    assert controller.phase == GridSearchPhase.FINISHED
    assert controller.is_active is False
    assert controller.compute(0.0, 0.0, 0.0, None, 0.1) is None


def test_compute_returns_none_when_position_telemetry_is_missing():
    controller = make_controller()
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0)
    assert controller.compute(current_lat=None, current_lon=0.0, current_heading_deg=0.0, current_altitude_m=None, dt=0.1) is None
    assert controller.compute(current_lat=0.0, current_lon=None, current_heading_deg=0.0, current_altitude_m=None, dt=0.1) is None
    assert controller.compute(current_lat=0.0, current_lon=0.0, current_heading_deg=None, current_altitude_m=None, dt=0.1) is None


def test_reset_clears_the_plan_and_returns_to_idle():
    controller = make_controller()
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0)
    controller.reset()
    assert controller.phase == GridSearchPhase.IDLE
    assert controller.status().waypoints == []
    assert controller.status().current_index == 0


def test_altitude_hold_engages_when_search_altitude_is_configured():
    controller = make_controller(search_altitude_m=30.0)
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0, heading_deg=0.0)
    status = controller.status()
    bearing_to_first = bearing_deg(0.0, 0.0, *status.waypoints[0])
    command = controller.compute(
        current_lat=0.0, current_lon=0.0, current_heading_deg=bearing_to_first,
        current_altitude_m=10.0, dt=0.1,  # 20m below the configured search altitude
    )
    assert command is not None
    assert command.vz_mps < 0.0  # NED: negative = climb, since it's below target altitude


def test_altitude_hold_is_a_noop_when_not_configured():
    controller = make_controller(search_altitude_m=None)
    controller.start(0.0, 0.0, width_m=100.0, height_m=40.0, heading_deg=0.0)
    status = controller.status()
    bearing_to_first = bearing_deg(0.0, 0.0, *status.waypoints[0])
    command = controller.compute(
        current_lat=0.0, current_lon=0.0, current_heading_deg=bearing_to_first,
        current_altitude_m=10.0, dt=0.1,
    )
    assert command is not None
    assert command.vz_mps == 0.0
