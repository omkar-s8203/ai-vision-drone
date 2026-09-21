"""Tests for tools/detection_regression.py.

analyze_session() is a pure function over plain dicts - fully testable
without any camera/detector. capture_session() is exercised here against
SyntheticCamera/PassthroughDetector; the real capture path
(Picamera2IMX500Camera/IMX500Detector) can only be run for real on the Pi.
"""

import pytest

from companion.vision.camera import SyntheticCamera
from companion.vision.detector import BBox, Detection, PassthroughDetector
from tools.detection_regression import analyze_session, capture_session


def _frame(detections):
    return {"detections": detections}


def _det(class_name="person", score=0.8, x=0.0, y=0.0, w=10.0, h=10.0):
    return {"class_name": class_name, "score": score, "x": x, "y": y, "w": w, "h": h}


def test_analyze_session_computes_detection_rate():
    frames = [_frame([_det()]), _frame([]), _frame([_det()]), _frame([_det()])]
    report = analyze_session(frames)
    assert report.total_frames == 4
    assert report.frames_with_detection == 3
    assert report.detection_rate == pytest.approx(0.75)


def test_analyze_session_finds_the_longest_zero_detection_gap():
    frames = [
        _frame([_det()]),
        _frame([]),
        _frame([]),
        _frame([]),
        _frame([_det()]),
        _frame([]),
    ]
    report = analyze_session(frames)
    assert report.longest_zero_detection_gap == 3


def test_analyze_session_with_no_gaps_reports_zero():
    frames = [_frame([_det()]) for _ in range(5)]
    report = analyze_session(frames)
    assert report.longest_zero_detection_gap == 0


def test_analyze_session_computes_score_statistics():
    frames = [_frame([_det(score=0.6)]), _frame([_det(score=0.8)]), _frame([])]
    report = analyze_session(frames)
    assert report.top_score_mean == pytest.approx(0.7)
    assert report.top_score_stdev is not None


def test_analyze_session_computes_bbox_jitter_for_the_same_class():
    frames = [
        _frame([_det(x=100.0, y=100.0)]),
        _frame([_det(x=103.0, y=104.0)]),  # 5px jitter (3-4-5 triangle)
    ]
    report = analyze_session(frames)
    assert report.bbox_jitter_px_mean == pytest.approx(5.0)
    assert report.bbox_jitter_px_max == pytest.approx(5.0)


def test_analyze_session_does_not_measure_jitter_across_a_class_change():
    frames = [_frame([_det(class_name="person", x=0.0)]), _frame([_det(class_name="car", x=500.0)])]
    report = analyze_session(frames)
    assert report.bbox_jitter_px_mean is None


def test_analyze_session_handles_an_empty_session_without_crashing():
    report = analyze_session([])
    assert report.total_frames == 0
    assert report.detection_rate == 0.0
    assert report.longest_zero_detection_gap == 0
    assert report.top_score_mean is None
    assert report.bbox_jitter_px_mean is None
    assert "0" in report.report()  # must not raise formatting real numbers


def test_analyze_session_handles_a_session_with_zero_detections_ever():
    frames = [_frame([]) for _ in range(3)]
    report = analyze_session(frames)
    assert report.longest_zero_detection_gap == 3
    assert report.top_score_mean is None


@pytest.mark.asyncio
async def test_capture_session_records_real_detections_from_a_known_source():
    real_detection = Detection(
        bbox=BBox(10.0, 20.0, 30.0, 40.0), score=0.91, class_id=0, class_name="person", frame_ts=0.0
    )
    camera = SyntheticCamera(
        width=640, height=480, target_fps=20, detection_source=lambda _ts: [real_detection]
    )
    detector = PassthroughDetector()

    frames = await capture_session(camera, detector, duration_s=0.2)

    assert len(frames) >= 2
    for frame in frames:
        assert frame["detections"] == [
            {"class_name": "person", "score": 0.91, "x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}
        ]
