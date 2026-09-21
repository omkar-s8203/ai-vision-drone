from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in meters. Ignores
    altitude - adequate for a horizontal "how far from home" estimate, not
    meant for precision navigation."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing (0-360, 0=true north) from point 1 to point
    2 - standard forward-azimuth formula. Used for the home-direction
    needle on the Android Status tab's radar widget (bearing from the
    aircraft's current position to home)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(lat: float, lon: float, bearing_deg_: float, distance_m: float) -> tuple[float, float]:
    """The "direct" geodesic problem, the inverse of bearing_deg/
    haversine_distance_m above (same spherical-Earth model, same
    EARTH_RADIUS_M): given a start point, a bearing, and a distance,
    returns the resulting (lat, lon). Used by generate_lawnmower_waypoints
    below to lay out a grid-search area from a single starting corner
    (docs plan M16 "future scalability" search/coverage idea) without
    needing a full local-ENU coordinate frame anywhere in this project."""
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)
    theta = math.radians(bearing_deg_)
    delta = distance_m / EARTH_RADIUS_M

    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lambda2) + 540) % 360 - 180


def generate_lawnmower_waypoints(
    start_lat: float,
    start_lon: float,
    width_m: float,
    height_m: float,
    spacing_m: float,
    heading_deg: float = 0.0,
) -> list[tuple[float, float]]:
    """A systematic area-sweep ("lawnmower"/boustrophedon) pattern covering
    a width_m x height_m rectangle, one corner anchored at (start_lat,
    start_lon) - a field request for a recon/surveillance-relevant "search/
    grid coverage mode," extending the existing single-target yaw-sweep
    search (companion/guidance/target_recovery.py) into area coverage
    instead of searching in place.

    `heading_deg` orients the rectangle (0 = the "height" side runs true
    north, sweep legs run east-west; a nonzero value rotates the whole
    rectangle, e.g. to align with a runway or a boundary that isn't
    itself north-aligned). Legs alternate direction each row (the actual
    "lawnmower" part) so the path is a single continuous, flyable line
    with no gaps or dead-heading backtracks between rows.

    Returns a flat list of (lat, lon) turn points - at least 2 per row
    (the two ends of that row's leg), `ceil(height_m / spacing_m) + 1`
    rows. A `spacing_m` at or above `height_m` degenerates to a single
    row (the whole area is "covered" in one pass at that spacing), which
    is a config problem for the caller to avoid, not something this
    function needs to reject.
    """
    num_rows = max(1, math.ceil(height_m / spacing_m) + 1)
    waypoints: list[tuple[float, float]] = []
    for row in range(num_rows):
        row_offset_m = min(row * spacing_m, height_m)
        # Both ends of this row are computed from the same fixed edge
        # (the "west" one, directly along heading_deg from the start
        # corner) so consecutive rows' matching ends line up exactly one
        # spacing_m apart - what actually makes appending them in
        # alternating order below produce one continuous connected path,
        # not a set of disconnected parallel legs.
        west_end = destination_point(start_lat, start_lon, heading_deg, row_offset_m)
        east_end = destination_point(west_end[0], west_end[1], (heading_deg + 90.0) % 360.0, width_m)
        if row % 2 == 0:
            waypoints.append(west_end)
            waypoints.append(east_end)
        else:
            waypoints.append(east_end)
            waypoints.append(west_end)
    return waypoints
