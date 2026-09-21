import pytest

from companion.main import build_tracker
from companion.tracking.bytetrack_impl import ByteTrackTracker
from companion.tracking.iou_tracker import IouKalmanTracker


def test_default_config_selects_iou_tracker():
    """Real hardware has only ever run IouKalmanTracker - the default must
    stay IouKalmanTracker even with no tracker section in hardware.yaml at
    all, so existing deployments aren't silently switched to the
    never-run-on-real-hardware ByteTrackTracker."""
    assert isinstance(build_tracker({}), IouKalmanTracker)


def test_explicit_iou_impl_selects_iou_tracker():
    assert isinstance(build_tracker({"tracker": {"impl": "iou"}}), IouKalmanTracker)


def test_bytetrack_impl_selects_bytetrack_tracker():
    tracker = build_tracker({"tracker": {"impl": "bytetrack"}})
    assert isinstance(tracker, ByteTrackTracker)


def test_bytetrack_impl_passes_through_its_own_tuning_params():
    tracker = build_tracker(
        {
            "tracker": {
                "impl": "bytetrack",
                "high_score_thresh": 0.7,
                "low_score_thresh": 0.2,
                "min_iou": 0.4,
            }
        }
    )
    assert tracker.high_score_thresh == 0.7
    assert tracker.low_score_thresh == 0.2
    assert tracker.min_iou == 0.4


def test_unknown_impl_raises_instead_of_silently_falling_back():
    """A typo in hardware.yaml's tracker.impl (e.g. 'byte_track') must be
    loud, not a silent fallback to a different tracker than the operator
    intended for that session."""
    with pytest.raises(ValueError, match="byte_track"):
        build_tracker({"tracker": {"impl": "byte_track"}})


def test_real_hardware_yaml_defaults_to_iou():
    from companion.config.loader import load_yaml

    hardware_cfg = load_yaml("hardware.yaml")
    assert isinstance(build_tracker(hardware_cfg), IouKalmanTracker)
