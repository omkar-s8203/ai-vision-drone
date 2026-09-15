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
