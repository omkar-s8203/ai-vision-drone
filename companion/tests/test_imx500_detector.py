import numpy as np
import pytest

from companion.vision.detector import IMX500Detector


class FakeIMX500:
    """Stands in for picamera2.devices.IMX500.convert_inference_coords -
    the real signature/behavior was confirmed against actual AI Camera
    hardware (docs plan M2): takes (y0, x0, y1, x1) normalized and returns
    pixel-space (x, y, w, h)."""

    def convert_inference_coords(self, coords, metadata, picam2):
        y0, x0, y1, x1 = coords
        return (x0 * 100, y0 * 100, (x1 - x0) * 100, (y1 - y0) * 100)


def make_outputs(boxes, scores, classes, count):
    """Matches the real confirmed shape: outputs[0][0]=boxes (N,4),
    outputs[1][0]=scores (N,), outputs[2][0]=classes (N,), outputs[3][0]=[count]."""
    return [
        np.array([boxes], dtype=np.float32),
        np.array([scores], dtype=np.float32),
        np.array([classes], dtype=np.float32),
        np.array([[count]], dtype=np.float32),
    ]


LABELS = ["person", "bicycle", "car", "motorcycle", "airplane", "bus"]


def test_parses_detections_above_threshold():
    outputs = make_outputs(
        boxes=[[0.1, 0.2, 0.5, 0.6], [0.0, 0.0, 0.1, 0.1]],
        scores=[0.9, 0.2],
        classes=[0, 5],
        count=2,
    )
    detector = IMX500Detector(class_names=LABELS, score_threshold=0.5)

    detections = detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)

    assert len(detections) == 1
    det = detections[0]
    assert det.class_name == "person"
    assert det.score == pytest.approx(0.9, abs=1e-6)
    assert det.bbox.x == pytest.approx(20.0, abs=1e-4)
    assert det.bbox.y == pytest.approx(10.0, abs=1e-4)
    assert det.bbox.w == pytest.approx(40.0, abs=1e-4)
    assert det.bbox.h == pytest.approx(40.0, abs=1e-4)


def test_returns_none_when_outputs_none():
    """Normal for ~1s after Picamera2.start() and intermittently afterwards -
    never an error, and never "saw nothing" ([]): the orchestrator must be able
    to tell a frame with no AI result from one where the target is gone."""
    detector = IMX500Detector(class_names=LABELS)
    assert detector.parse((FakeIMX500(), None, {}, None), frame_ts=1.0) is None


def test_returns_empty_list_when_the_model_ran_and_found_nothing():
    detector = IMX500Detector(class_names=LABELS)
    outputs = make_outputs(boxes=[[0.1, 0.2, 0.5, 0.6]], scores=[0.9], classes=[0], count=0)
    assert detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0) == []


def test_count_limits_how_many_entries_are_considered():
    outputs = make_outputs(
        boxes=[[0.0, 0.0, 0.2, 0.2], [0.0, 0.0, 0.2, 0.2]],
        scores=[0.9, 0.9],
        classes=[0, 0],
        count=1,  # only the first entry is valid
    )
    detector = IMX500Detector(class_names=LABELS, score_threshold=0.5)

    detections = detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)

    assert len(detections) == 1


def test_unknown_class_id_falls_back():
    outputs = make_outputs(boxes=[[0.0, 0.0, 0.2, 0.2]], scores=[0.8], classes=[99], count=1)
    detector = IMX500Detector(class_names=LABELS, score_threshold=0.5)

    detections = detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)

    assert detections[0].class_name == "unknown"


def test_dict_class_names_still_supported():
    outputs = make_outputs(boxes=[[0.0, 0.0, 0.2, 0.2]], scores=[0.8], classes=[2], count=1)
    detector = IMX500Detector(class_names={2: "car"}, score_threshold=0.5)

    detections = detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)

    assert detections[0].class_name == "car"


def test_logs_a_diagnostic_warning_when_outputs_is_none(caplog):
    """A field report of 'clear, well-lit subject, zero detections' is
    invisible from the Android app's health panel alone (that only
    reflects a heartbeat, not real detection activity) - this rate-limited
    warning is what should show up in `journalctl -u ai-vision-drone -f`
    to tell apart 'the on-sensor network isn't running at all' from a
    score_threshold problem."""
    detector = IMX500Detector(class_names=LABELS, diagnostic_log_interval_s=0.0)
    with caplog.at_level("WARNING"):
        detector.parse((FakeIMX500(), None, {}, None), frame_ts=1.0)
    assert any("outputs is None" in r.message for r in caplog.records)


def test_logs_a_diagnostic_warning_when_zero_candidates(caplog):
    outputs = make_outputs(boxes=[], scores=[], classes=[], count=0)
    detector = IMX500Detector(class_names=LABELS, diagnostic_log_interval_s=0.0)
    with caplog.at_level("WARNING"):
        detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)
    assert any("0 candidate" in r.message for r in caplog.records)


def test_logs_a_diagnostic_warning_when_everything_is_below_threshold(caplog):
    outputs = make_outputs(boxes=[[0.0, 0.0, 0.2, 0.2]], scores=[0.3], classes=[0], count=1)
    detector = IMX500Detector(class_names=LABELS, score_threshold=0.5, diagnostic_log_interval_s=0.0)
    with caplog.at_level("WARNING"):
        detections = detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)
    assert detections == []
    assert any("below score_threshold" in r.message for r in caplog.records)


def test_diagnostic_logging_is_rate_limited(caplog):
    outputs = make_outputs(boxes=[], scores=[], classes=[], count=0)
    detector = IMX500Detector(class_names=LABELS, diagnostic_log_interval_s=1000.0)
    with caplog.at_level("WARNING"):
        detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)
        detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.1)
    assert len(caplog.records) == 1  # the second call is within the interval, so it's suppressed


def test_no_diagnostic_log_when_a_real_detection_is_found(caplog):
    outputs = make_outputs(boxes=[[0.0, 0.0, 0.2, 0.2]], scores=[0.9], classes=[0], count=1)
    detector = IMX500Detector(class_names=LABELS, score_threshold=0.5, diagnostic_log_interval_s=0.0)
    with caplog.at_level("WARNING"):
        detections = detector.parse((FakeIMX500(), outputs, {}, None), frame_ts=1.0)
    assert len(detections) == 1
    assert caplog.records == []
