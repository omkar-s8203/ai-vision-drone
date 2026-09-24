import pytest

from companion.config.loader import load_yaml
from companion.guidance.orbit import OrbitController
from companion.tracking.base import TrackedTarget
from companion.vision.detector import BBox

LIMITS = load_yaml("orbit_limits.yaml")
IMAGE_W, IMAGE_H = 1280, 720


def make_target(cx, cy, w=50, h=100):
    return TrackedTarget(
        target_id=1,
        bbox=BBox(cx - w / 2, cy - h / 2, w, h),
        confidence=0.9,
        class_id=0,
        class_name="person",
        last_seen_ts=0.0,
    )


def test_too_far_produces_forward_velocity_toward_target():
    controller = OrbitController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=20.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps > 0


def test_too_close_produces_backward_velocity():
    controller = OrbitController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=2.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps < 0


def test_at_configured_radius_produces_a_tangential_strafe():
    """Even holding the exact orbit radius, the drone must keep moving
    sideways (vy != 0) - that's what actually produces the circling motion,
    unlike Follow where centered-at-distance means fully stationary."""
    controller = OrbitController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=LIMITS["orbit_radius_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.vx_mps == 0.0
    assert cmd.vy_mps != 0.0


def test_clockwise_direction_produces_positive_strafe():
    limits = load_yaml("orbit_limits.yaml")
    limits["direction"] = 1
    controller = OrbitController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["orbit_radius_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.vy_mps > 0


def test_counter_clockwise_direction_produces_negative_strafe():
    limits = load_yaml("orbit_limits.yaml")
    limits["direction"] = -1
    controller = OrbitController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["orbit_radius_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.vy_mps < 0


def test_lateral_offset_beyond_deadband_produces_yaw_rate():
    controller = OrbitController(LIMITS)
    target = make_target(IMAGE_W / 2 + 200, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=LIMITS["orbit_radius_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.yaw_rate_rads != 0.0


def test_no_distance_estimate_zeroes_forward_velocity_but_still_orbits():
    controller = OrbitController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=None, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == 0.0
    assert cmd.vy_mps != 0.0  # falls back to the configured orbit_radius_m


def test_output_respects_max_speed_limit():
    controller = OrbitController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=1000.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps <= LIMITS["max_speed_mps"]
    assert abs(cmd.vy_mps) <= LIMITS["max_speed_mps"]


def test_altitude_hold_climbs_when_below_target_altitude():
    limits = load_yaml("orbit_limits.yaml")
    limits["target_altitude_m"] = 10.0
    controller = OrbitController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["orbit_radius_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=5.0,
    )
    assert cmd.vz_mps < 0  # NED: negative = climb


def test_set_max_speed_actually_lowers_the_pid_internal_cap():
    """See FollowController's identical test for the real bug this guards
    against - each PID's out_limit is baked in at construction, so a naive
    dict-only update would leave it stuck at the old (higher) value."""
    limits = load_yaml("orbit_limits.yaml")
    controller = OrbitController(limits)
    controller.set_max_speed(1.0)
    assert limits["max_speed_mps"] == 1.0
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    for _ in range(40):  # let the acceleration limit finish ramping up
        cmd = controller.compute(target, distance_m=1000.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == pytest.approx(1.0)


def test_set_max_speed_cannot_exceed_the_configured_ceiling():
    limits = load_yaml("orbit_limits.yaml")
    ceiling = limits["max_speed_mps"]
    controller = OrbitController(limits)
    controller.set_max_speed(ceiling + 50.0)
    assert limits["max_speed_mps"] == ceiling


def test_set_max_speed_cannot_go_below_the_configured_floor():
    limits = load_yaml("orbit_limits.yaml")
    floor = limits["min_speed_mps"]
    controller = OrbitController(limits)
    controller.set_max_speed(-5.0)
    assert limits["max_speed_mps"] == floor
