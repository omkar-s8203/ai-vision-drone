from companion.config.loader import load_yaml
from companion.guidance.smart_shot import ShotType, SmartShotController, SmartShotState
from companion.tracking.base import TrackedTarget
from companion.vision.detector import BBox

LIMITS = load_yaml("smart_shot_limits.yaml")
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


def test_idle_by_default_returns_no_command():
    controller = SmartShotController(LIMITS)
    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.1)
    assert result.state == SmartShotState.IDLE
    assert result.command is None


def test_dronie_retreats_backward_and_climbs():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.DRONIE)
    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.1)
    assert result.state == SmartShotState.RUNNING
    assert result.command.vx_mps < 0  # backward, away from target
    assert result.command.vz_mps < 0  # NED: negative = climbing


def test_parabola_translates_forward_and_climbs_early():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.PARABOLA)
    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.1)
    assert result.command.vx_mps > 0  # translating past the target
    assert result.command.vz_mps < 0  # early in the shot: climbing


def test_parabola_descends_in_the_second_half():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.PARABOLA)
    duration = LIMITS["duration_s"]
    # Advance past the midpoint of the arc.
    controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=duration * 0.75)
    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.01)
    assert result.command.vz_mps > 0  # descending back down


def test_shot_finishes_after_duration_and_sends_a_final_zero_command():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.DRONIE)
    duration = LIMITS["duration_s"]
    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=duration + 1.0)
    assert result.state == SmartShotState.FINISHED
    assert result.command.vx_mps == 0.0
    assert result.command.vy_mps == 0.0
    assert result.command.vz_mps == 0.0
    assert result.command.yaw_rate_rads == 0.0


def test_no_further_commands_after_finished():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.DRONIE)
    duration = LIMITS["duration_s"]
    controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=duration + 1.0)

    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.1)

    assert result.state == SmartShotState.FINISHED
    assert result.command is None


def test_stop_returns_to_idle_and_clears_shot_type():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.PARABOLA)

    controller.stop()

    assert controller.is_active is False
    result = controller.update(make_target(IMAGE_W / 2, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.1)
    assert result.state == SmartShotState.IDLE
    assert result.command is None


def test_lateral_offset_beyond_deadband_produces_yaw_rate():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.DRONIE)
    result = controller.update(make_target(IMAGE_W / 2 + 200, IMAGE_H / 2), IMAGE_W, IMAGE_H, dt=0.1)
    assert result.command.yaw_rate_rads != 0.0


def test_no_target_still_produces_translation_but_no_yaw():
    controller = SmartShotController(LIMITS)
    controller.start(ShotType.DRONIE)
    result = controller.update(None, IMAGE_W, IMAGE_H, dt=0.1)
    assert result.command.vx_mps < 0
    assert result.command.yaw_rate_rads == 0.0
