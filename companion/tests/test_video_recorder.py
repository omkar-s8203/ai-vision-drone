import numpy as np

from companion.comms.video_recorder import VideoRecorder


def test_start_creates_file_and_marks_recording(tmp_path):
    recorder = VideoRecorder(tmp_path, fps=10)
    assert recorder.is_recording is False

    path = recorder.start(width=64, height=48)

    assert recorder.is_recording is True
    assert path.parent == tmp_path
    recorder.stop()


def test_write_and_stop_produces_a_real_file(tmp_path):
    recorder = VideoRecorder(tmp_path, fps=10)
    recorder.start(width=64, height=48)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    for _ in range(5):
        recorder.write(frame)
    path = recorder.stop()

    assert path is not None
    assert path.exists()
    assert path.stat().st_size > 0
    assert recorder.is_recording is False


def test_write_before_start_is_a_safe_no_op(tmp_path):
    recorder = VideoRecorder(tmp_path, fps=10)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    recorder.write(frame)  # must not raise


def test_start_twice_is_idempotent(tmp_path):
    recorder = VideoRecorder(tmp_path, fps=10)
    path1 = recorder.start(width=64, height=48)
    path2 = recorder.start(width=64, height=48)
    assert path1 == path2
    recorder.stop()


def test_stop_without_start_returns_none(tmp_path):
    recorder = VideoRecorder(tmp_path, fps=10)
    assert recorder.stop() is None
