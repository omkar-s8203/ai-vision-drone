"""Tests for companion/vision/camera.py's open_real_camera_and_detector()
- the shared real-hardware camera/detector factory used by
tools/benchmark_detection.py and tools/detection_regression.py.

Picamera2IMX500Camera itself needs the real picamera2 package (only
installed on a Pi), so its construction is mocked here to control exactly
what it raises - this dev machine can't reproduce the real
"Device or resource busy" OSError, but it can prove the wrapper reacts to
it correctly."""

from unittest.mock import patch

import pytest

from companion.vision.camera import open_real_camera_and_detector

HARDWARE_CFG = {
    "camera": {
        "imx500_model_path": "/fake/model.rpk",
        "width": 1280,
        "height": 720,
        "target_fps": 30,
    }
}


def test_gives_an_actionable_message_when_the_camera_is_already_busy():
    """A real field report: a bare `OSError: [Errno 16] Device or resource
    busy` from deep inside picamera2/V4L2, with no indication that the
    likely cause is the ai-vision-drone systemd service already holding
    the camera open."""
    with patch("companion.vision.camera.Picamera2IMX500Camera") as mock_camera_cls:
        mock_camera_cls.side_effect = OSError(16, "Device or resource busy")
        with pytest.raises(RuntimeError) as excinfo:
            open_real_camera_and_detector(HARDWARE_CFG)
    assert "systemctl stop ai-vision-drone" in str(excinfo.value)


def test_reraises_unrelated_camera_errors_unchanged():
    with patch("companion.vision.camera.Picamera2IMX500Camera") as mock_camera_cls:
        mock_camera_cls.side_effect = RuntimeError("some other real failure")
        with pytest.raises(RuntimeError, match="some other real failure"):
            open_real_camera_and_detector(HARDWARE_CFG)


def test_builds_a_detector_from_the_real_camera_s_labels_and_configured_threshold():
    cfg = {**HARDWARE_CFG, "camera": {**HARDWARE_CFG["camera"], "score_threshold": 0.42}}
    with patch("companion.vision.camera.Picamera2IMX500Camera") as mock_camera_cls:
        mock_instance = mock_camera_cls.return_value
        mock_instance.imx500.network_intrinsics.labels = ["person", "car"]

        camera, detector = open_real_camera_and_detector(cfg)

    assert camera is mock_instance
    assert detector.class_names == ["person", "car"]
    assert detector.score_threshold == 0.42


def test_defaults_score_threshold_when_not_configured():
    with patch("companion.vision.camera.Picamera2IMX500Camera") as mock_camera_cls:
        mock_instance = mock_camera_cls.return_value
        mock_instance.imx500.network_intrinsics.labels = ["person"]

        _camera, detector = open_real_camera_and_detector(HARDWARE_CFG)

    assert detector.score_threshold == 0.5
