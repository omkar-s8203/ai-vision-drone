import pytest

from companion.guidance.geo import bearing_deg, haversine_distance_m


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
