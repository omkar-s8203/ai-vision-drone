import pytest

from companion.guidance.geo import (
    bearing_deg,
    destination_point,
    generate_lawnmower_waypoints,
    haversine_distance_m,
)


def test_same_point_is_zero_distance():
    assert haversine_distance_m(37.7749, -122.4194, 37.7749, -122.4194) == pytest.approx(0.0, abs=1e-6)


def test_one_degree_longitude_at_equator_is_about_111km():
    # A well-known reference value: 1 degree of longitude at the equator
    # is ~111.19 km - a sanity check against a real geodesy fact, not an
    # arbitrary tolerance.
    distance = haversine_distance_m(0.0, 0.0, 0.0, 1.0)
    assert distance == pytest.approx(111_195, rel=0.01)


def test_small_real_world_offset_is_a_sane_meters_value():
    # Roughly 100m north (0.0009 degrees latitude is ~100m).
    distance = haversine_distance_m(37.7749, -122.4194, 37.7758, -122.4194)
    assert 90 < distance < 110


def test_antipodal_points_are_about_half_earth_circumference():
    distance = haversine_distance_m(0.0, 0.0, 0.0, 180.0)
    assert distance == pytest.approx(20_015_000, rel=0.01)


def test_bearing_due_north_is_zero():
    assert bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-6)


def test_bearing_due_east_is_ninety():
    assert bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=0.1)


def test_bearing_due_south_is_180():
    assert bearing_deg(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0, abs=1e-6)


def test_bearing_due_west_is_270():
    assert bearing_deg(0.0, 0.0, 0.0, -1.0) == pytest.approx(270.0, abs=0.1)


def test_bearing_is_always_in_0_360_range():
    assert 0.0 <= bearing_deg(37.7749, -122.4194, 37.7758, -122.4200) < 360.0


def test_destination_point_with_zero_distance_returns_the_same_point():
    lat, lon = destination_point(37.7749, -122.4194, 45.0, 0.0)
    assert lat == pytest.approx(37.7749, abs=1e-9)
    assert lon == pytest.approx(-122.4194, abs=1e-9)


def test_destination_point_due_north_matches_the_known_111km_reference():
    # Mirrors test_one_degree_longitude_at_equator_is_about_111km's own
    # reference fact, just walked forward instead of measured backward.
    lat, lon = destination_point(0.0, 0.0, 0.0, 111_195)
    assert lat == pytest.approx(1.0, abs=0.01)
    assert lon == pytest.approx(0.0, abs=1e-6)


def test_destination_point_is_the_true_inverse_of_bearing_and_distance():
    """destination_point (the "direct" geodesic problem) and
    bearing_deg/haversine_distance_m (the "inverse" problem) must agree
    with each other on the same spherical model - walking from a point by
    a given bearing/distance, then measuring the bearing/distance back to
    where you started from, should recover the original inputs."""
    start_lat, start_lon = 37.7749, -122.4194
    bearing, distance = 217.0, 850.0
    dest_lat, dest_lon = destination_point(start_lat, start_lon, bearing, distance)

    assert haversine_distance_m(start_lat, start_lon, dest_lat, dest_lon) == pytest.approx(distance, rel=1e-3)
    assert bearing_deg(start_lat, start_lon, dest_lat, dest_lon) == pytest.approx(bearing, abs=0.1)


def test_lawnmower_waypoints_first_point_is_the_given_start_corner():
    waypoints = generate_lawnmower_waypoints(0.0, 0.0, width_m=100.0, height_m=50.0, spacing_m=20.0)
    assert waypoints[0] == pytest.approx((0.0, 0.0), abs=1e-9)


def test_lawnmower_waypoints_row_count_matches_height_and_spacing():
    # ceil(50/20) + 1 = 4 rows, 2 waypoints (a leg's two ends) per row.
    waypoints = generate_lawnmower_waypoints(0.0, 0.0, width_m=100.0, height_m=50.0, spacing_m=20.0)
    assert len(waypoints) == 8


def test_lawnmower_waypoints_each_leg_covers_the_requested_width():
    waypoints = generate_lawnmower_waypoints(10.0, 20.0, width_m=200.0, height_m=60.0, spacing_m=15.0)
    for i in range(0, len(waypoints), 2):
        leg_start, leg_end = waypoints[i], waypoints[i + 1]
        leg_length = haversine_distance_m(leg_start[0], leg_start[1], leg_end[0], leg_end[1])
        assert leg_length == pytest.approx(200.0, rel=0.01)


def test_lawnmower_waypoints_rows_are_spaced_along_the_height_axis():
    """Each row's "west" (heading-aligned) edge should sit row*spacing_m
    along the sweep heading from the start corner - the actual "coverage"
    part of the pattern, not just a bunch of same-spot legs. (The two
    waypoints appended per row alternate which one is the "west" edge -
    index 2*row when the row is even, 2*row+1 when odd - see
    generate_lawnmower_waypoints' own alternating append order.)"""
    waypoints = generate_lawnmower_waypoints(0.0, 0.0, width_m=100.0, height_m=60.0, spacing_m=20.0, heading_deg=0.0)
    num_rows = len(waypoints) // 2
    for row in range(num_rows):
        west_index = 2 * row if row % 2 == 0 else 2 * row + 1
        expected_offset_m = min(row * 20.0, 60.0)
        actual_offset_m = haversine_distance_m(0.0, 0.0, *waypoints[west_index])
        assert actual_offset_m == pytest.approx(expected_offset_m, abs=1.0)


def test_lawnmower_waypoints_alternate_sweep_direction_each_row():
    """The actual "lawnmower" behavior: row 0 sweeps one way, row 1 sweeps
    back the other way, so consecutive rows connect with a short spacing_m
    hop to the adjacent row - never a long diagonal dead-head back across
    the whole width to start the next row from the same side again."""
    waypoints = generate_lawnmower_waypoints(0.0, 0.0, width_m=100.0, height_m=60.0, spacing_m=20.0)
    # Row 0 ends adjacent to where row 1 starts (waypoints[1] and
    # waypoints[2]) - a short spacing_m connecting hop, not a fresh
    # width_m-long leg starting back on the same side.
    row0_end = waypoints[1]
    row1_start = waypoints[2]
    assert haversine_distance_m(*row0_end, *row1_start) == pytest.approx(20.0, rel=0.02)


def test_lawnmower_waypoints_with_tiny_height_still_produces_at_least_one_leg():
    waypoints = generate_lawnmower_waypoints(0.0, 0.0, width_m=50.0, height_m=1.0, spacing_m=20.0)
    assert len(waypoints) >= 2
