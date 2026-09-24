import pytest

from companion.config.loader import load_yaml
from companion.guidance.follow import FollowController
from companion.guidance.limits import SlewLimiter, apply_altitude_limits, clamp_to_range
from companion.guidance.orbit import OrbitController
from companion.tracking.base import TrackedTarget
from companion.vision.detector import BBox

IMAGE_W, IMAGE_H = 1280, 720


def make_target(cx, cy, w=50, h=100):
    return TrackedTarget(
        target_id=1, bbox=BBox(cx - w / 2, cy - h / 2, w, h), confidence=0.9,
        class_id=0, class_name="person", last_seen_ts=0.0,
    )


def _distance_for(limits):
    return limits.get("target_separation_m", limits.get("orbit_radius_m"))


# --- SlewLimiter -----------------------------------------------------------

def test_slew_limiter_ramps_at_the_configured_acceleration():
    limiter = SlewLimiter(max_accel_mps2=2.0)
    assert limiter.step(10.0, 0.1) == pytest.approx(0.2)
    assert limiter.step(10.0, 0.1) == pytest.approx(0.4)


def test_slew_limiter_limits_deceleration_too():
    limiter = SlewLimiter(max_accel_mps2=2.0)
    limiter.override(3.0)
    assert limiter.step(-3.0, 0.5) == pytest.approx(2.0)


def test_slew_limiter_reaches_a_nearby_target_exactly():
    limiter = SlewLimiter(max_accel_mps2=2.0)
    assert limiter.step(0.1, 1.0) == pytest.approx(0.1)


def test_slew_limiter_none_means_unlimited():
    limiter = SlewLimiter(None)
    assert limiter.step(9.0, 0.01) == 9.0


def test_slew_limiter_reset_returns_to_standstill():
    limiter = SlewLimiter(max_accel_mps2=2.0)
    limiter.step(10.0, 1.0)
    limiter.reset()
    assert limiter.step(10.0, 0.1) == pytest.approx(0.2)


def test_slew_limiter_zero_dt_does_not_move():
    limiter = SlewLimiter(max_accel_mps2=2.0)
    assert limiter.step(5.0, 0.0) == 0.0


# --- apply_altitude_limits -------------------------------------------------

def test_descent_refused_at_or_below_the_floor():
    assert apply_altitude_limits(1.0, 2.0, 2.0, 30.0) == 0.0
    assert apply_altitude_limits(1.0, 1.0, 2.0, 30.0) == 0.0


def test_descent_allowed_above_the_floor_and_climb_allowed_at_it():
    assert apply_altitude_limits(1.0, 5.0, 2.0, 30.0) == 1.0
    assert apply_altitude_limits(-1.0, 2.0, 2.0, 30.0) == -1.0


def test_climb_refused_at_or_above_the_ceiling():
    assert apply_altitude_limits(-1.0, 30.0, 2.0, 30.0) == 0.0
    assert apply_altitude_limits(1.0, 30.0, 2.0, 30.0) == 1.0


def test_unknown_altitude_suppresses_descent_but_allows_climb():
    assert apply_altitude_limits(1.0, None, 2.0, 30.0) == 0.0
    assert apply_altitude_limits(-1.0, None, 2.0, 30.0) == -1.0


def test_no_configured_floor_means_no_restriction_even_without_telemetry():
    assert apply_altitude_limits(1.0, None, None, None) == 1.0


def test_clamp_to_range():
    assert clamp_to_range(0.1, 3.0, 15.0) == 3.0
    assert clamp_to_range(99.0, 3.0, 15.0) == 15.0
    assert clamp_to_range(7.0, 3.0, 15.0) == 7.0
    assert clamp_to_range(7.0, None, None) == 7.0


# --- Follow / Orbit enforce them ------------------------------------------

@pytest.mark.parametrize("controller_cls,limits_file", [
    (FollowController, "follow_limits.yaml"),
    (OrbitController, "orbit_limits.yaml"),
])
def test_pixel_framing_never_descends_below_the_altitude_floor(controller_cls, limits_file):
    """Regression for a real gap: pixel-framing vertical control commanded a
    descent whenever the target sat below the image center, with no floor -
    min_altitude_m in the config was never enforced anywhere."""
    limits = load_yaml(limits_file)
    controller = controller_cls(limits)
    target_below_center = make_target(IMAGE_W / 2, IMAGE_H / 2 + 250)
    for _ in range(20):
        cmd = controller.compute(
            target_below_center, distance_m=_distance_for(limits),
            image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1,
            current_altitude_m=limits["min_altitude_m"],
        )
        assert cmd.vz_mps <= 0.0


@pytest.mark.parametrize("controller_cls,limits_file", [
    (FollowController, "follow_limits.yaml"),
    (OrbitController, "orbit_limits.yaml"),
])
def test_pixel_framing_still_descends_when_well_above_the_floor(controller_cls, limits_file):
    limits = load_yaml(limits_file)
    controller = controller_cls(limits)
    target_below_center = make_target(IMAGE_W / 2, IMAGE_H / 2 + 250)
    cmd = None
    for _ in range(5):
        cmd = controller.compute(
            target_below_center, distance_m=_distance_for(limits),
            image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1, current_altitude_m=20.0,
        )
    assert cmd.vz_mps > 0.0


def test_altitude_hold_cannot_command_a_descent_through_the_floor():
    limits = load_yaml("follow_limits.yaml")
    limits["target_altitude_m"] = 1.0  # below the floor
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=limits["min_altitude_m"],
    )
    assert cmd.vz_mps <= 0.0


def test_no_descent_without_altitude_telemetry():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2 + 250)
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=None,
    )
    assert cmd.vz_mps <= 0.0


def test_ceiling_blocks_further_climb():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    target_above_center = make_target(IMAGE_W / 2, IMAGE_H / 2 - 250)
    for _ in range(10):
        cmd = controller.compute(
            target_above_center, distance_m=limits["target_separation_m"], image_width=IMAGE_W,
            image_height=IMAGE_H, dt=0.1, current_altitude_m=limits["max_altitude_m"],
        )
        assert cmd.vz_mps >= 0.0


def test_follow_forward_speed_ramps_instead_of_stepping():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    first = controller.compute(target, distance_m=50.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert first.vx_mps == pytest.approx(limits["max_accel_mps2"] * 0.1)
    speeds = [first.vx_mps]
    for _ in range(60):
        speeds.append(
            controller.compute(target, distance_m=50.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1).vx_mps
        )
    steps = [b - a for a, b in zip(speeds, speeds[1:])]
    assert max(steps) <= limits["max_accel_mps2"] * 0.1 + 1e-9
    assert speeds[-1] == pytest.approx(limits["max_speed_mps"])


def test_reset_puts_the_ramp_back_to_a_standstill():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    for _ in range(30):
        controller.compute(target, distance_m=50.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    controller.reset()
    cmd = controller.compute(target, distance_m=50.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == pytest.approx(limits["max_accel_mps2"] * 0.1)


def test_lowering_max_speed_takes_effect_immediately_despite_the_ramp():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    for _ in range(60):
        controller.compute(target, distance_m=50.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    controller.set_max_speed(1.0)
    cmd = controller.compute(target, distance_m=50.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps <= 1.0 + 1e-9


def test_orbit_tangential_speed_ramps_too():
    limits = load_yaml("orbit_limits.yaml")
    controller = OrbitController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["orbit_radius_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert abs(cmd.vy_mps) <= limits["max_accel_mps2"] * 0.1 + 1e-9


def test_guidance_bbox_is_used_when_present():
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2 + 300, IMAGE_H / 2)  # raw box far right
    target.smooth_bbox = BBox(IMAGE_W / 2 - 25, IMAGE_H / 2 - 50, 50, 100)  # filtered box centered
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.yaw_rate_rads == 0.0
