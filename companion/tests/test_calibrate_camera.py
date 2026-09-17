"""Tests for tools/calibrate_camera.py.

Scope note: these test the plumbing this script actually owns - file
globbing/skipping logic and input validation - not cv2.calibrateCamera()'s
own numerical fit, which is OpenCV's well-tested functionality, not ours.
A fully synthetic multi-view calibration accuracy test would need several
distinctly-posed checkerboard renders and risks being flaky for a script
that's meant to be run once by a human against real photos anyway - not
worth building here.
"""

import numpy as np
import pytest

from tools.calibrate_camera import calibrate, find_corners

BOARD_SIZE = (5, 4)  # small on purpose - keeps the synthetic image tiny/fast


def make_checkerboard_image(board_size: tuple[int, int], square_px: int = 40, margin_px: int = 40) -> np.ndarray:
    """A perfect frontal checkerboard pattern - reliably detected by
    cv2.findChessboardCorners, which is all these tests need (they check
    the skip/collect logic around detection, not calibration accuracy)."""
    squares_x, squares_y = board_size[0] + 1, board_size[1] + 1
    width = squares_x * square_px + 2 * margin_px
    height = squares_y * square_px + 2 * margin_px
    image = np.full((height, width), 255, dtype=np.uint8)
    for row in range(squares_y):
        for col in range(squares_x):
            if (row + col) % 2 == 0:
                y0 = margin_px + row * square_px
                x0 = margin_px + col * square_px
                image[y0 : y0 + square_px, x0 : x0 + square_px] = 0
    import cv2

    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)


def make_blank_image(width: int = 100, height: int = 100) -> np.ndarray:
    return np.full((height, width, 3), 128, dtype=np.uint8)


def test_find_corners_detects_a_real_checkerboard(tmp_path):
    import cv2

    image = make_checkerboard_image(BOARD_SIZE)
    path = tmp_path / "good.png"
    cv2.imwrite(str(path), image)

    object_points, image_points, image_size = find_corners([str(path)], BOARD_SIZE)

    assert len(object_points) == 1
    assert len(image_points) == 1
    assert image_size == (image.shape[1], image.shape[0])


def test_find_corners_skips_an_image_with_no_checkerboard(tmp_path):
    import cv2

    path = tmp_path / "blank.png"
    cv2.imwrite(str(path), make_blank_image())

    object_points, image_points, image_size = find_corners([str(path)], BOARD_SIZE)

    assert object_points == []
    assert image_points == []


def test_find_corners_skips_an_unreadable_file(tmp_path):
    path = tmp_path / "not_an_image.txt"
    path.write_text("this is not image data")

    object_points, image_points, image_size = find_corners([str(path)], BOARD_SIZE)

    assert object_points == []
    assert image_size is None


def test_find_corners_skips_a_mismatched_resolution(tmp_path):
    import cv2

    good = make_checkerboard_image(BOARD_SIZE)
    good_path = tmp_path / "a.png"
    cv2.imwrite(str(good_path), good)

    wrong_size = make_checkerboard_image(BOARD_SIZE, square_px=20)  # different overall resolution
    wrong_path = tmp_path / "b.png"
    cv2.imwrite(str(wrong_path), wrong_size)

    object_points, image_points, image_size = find_corners([str(good_path), str(wrong_path)], BOARD_SIZE)

    # Only the first (which sets the expected resolution) is kept.
    assert len(object_points) == 1
    assert image_size == (good.shape[1], good.shape[0])


def test_calibrate_raises_with_too_few_usable_images():
    with pytest.raises(SystemExit):
        calibrate(object_points=[np.zeros((1, 3))], image_points=[np.zeros((1, 1, 2))], image_size=(100, 100))
