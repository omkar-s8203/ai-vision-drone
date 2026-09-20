import pytest

from companion.config.loader import load_yaml
from companion.guidance.follow import FollowController
from companion.tracking.base import TrackedTarget
from companion.vision.detector import BBox

LIMITS = load_yaml("follow_limits.yaml")
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


def test_too_far_produces_forward_velocity():
    controller = FollowController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=10.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps > 0


def test_too_close_produces_backward_velocity():
    controller = FollowController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=2.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps < 0


def test_centered_target_at_correct_distance_is_near_zero():
    controller = FollowController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=LIMITS["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.vx_mps == 0.0
    assert cmd.yaw_rate_rads == 0.0
    assert cmd.vz_mps == 0.0


def test_lateral_offset_beyond_deadband_produces_yaw_rate():
    controller = FollowController(LIMITS)
    target = make_target(IMAGE_W / 2 + 200, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=LIMITS["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1
    )
    assert cmd.yaw_rate_rads != 0.0


def test_no_distance_estimate_zeroes_forward_velocity():
    controller = FollowController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=None, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == 0.0


def test_output_respects_max_speed_limit():
    controller = FollowController(LIMITS)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=1000.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps <= LIMITS["max_speed_mps"]


def test_altitude_hold_climbs_when_below_target_altitude():
    limits = load_yaml("follow_limits.yaml")
    limits["target_altitude_m"] = 10.0
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=5.0,
    )
    assert cmd.vz_mps < 0  # NED: negative = climb


def test_altitude_hold_descends_when_above_target_altitude():
    limits = load_yaml("follow_limits.yaml")
    limits["target_altitude_m"] = 5.0
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=10.0,
    )
    assert cmd.vz_mps > 0


def test_altitude_hold_falls_back_to_pixel_framing_without_telemetry():
    limits = load_yaml("follow_limits.yaml")
    limits["target_altitude_m"] = 10.0
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2 + 200)  # off-center vertically
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=None,
    )
    assert cmd.vz_mps != 0.0


def test_no_altitude_configured_uses_pixel_framing_by_default():
    limits = load_yaml("follow_limits.yaml")
    assert limits["target_altitude_m"] is None
    controller = FollowController(limits)
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(
        target, distance_m=limits["target_separation_m"], image_width=IMAGE_W, image_height=IMAGE_H,
        dt=0.1, current_altitude_m=100.0,  # ignored since target_altitude_m is unset
    )
    assert cmd.vz_mps == 0.0


def test_set_max_speed_actually_lowers_the_pid_internal_cap():
    """A real bug this test guards against: each PID's out_limit is baked
    in at construction from the initial max_speed_mps - naively mutating
    limits["max_speed_mps"] alone (like the live separation/altitude
    updates do) would leave the PID's own internal clamp stuck at the old
    value, so only the redundant outer clamp in compute() would ever see
    the new number. This drives the distance error hard enough that the
    PID itself (not just the outer clamp) would saturate, and checks the
    lowered cap is actually respected."""
    limits = load_yaml("follow_limits.yaml")
    controller = FollowController(limits)
    controller.set_max_speed(1.0)
    assert limits["max_speed_mps"] == 1.0
    target = make_target(IMAGE_W / 2, IMAGE_H / 2)
    cmd = controller.compute(target, distance_m=1000.0, image_width=IMAGE_W, image_height=IMAGE_H, dt=0.1)
    assert cmd.vx_mps == pytest.approx(1.0)


def test_set_max_speed_cannot_exceed_the_configured_ceiling():
    """The Android speed slider must only ever dial speed DOWN from the
    safety-vetted config ceiling, never up past it from a phone
    mid-flight - a request above the ceiling is clamped, not honored."""
    limits = load_yaml("follow_limits.yaml")
    ceiling = limits["max_speed_mps"]
    controller = FollowController(limits)
    controller.set_max_speed(ceiling + 50.0)
    assert limits["max_speed_mps"] == ceiling


def test_set_max_speed_cannot_go_below_the_configured_floor():
    limits = load_yaml("follow_limits.yaml")
    floor = limits["min_speed_mps"]
    controller = FollowController(limits)
    controller.set_max_speed(-5.0)
    assert limits["max_speed_mps"] == floor
