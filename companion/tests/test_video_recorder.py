import threading
import time
from unittest.mock import MagicMock, patch

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


def test_start_returns_none_when_every_codec_fails_to_open(tmp_path):
    """Real bug found in the field: cv2.VideoWriter() never raises on
    failure, it just returns a writer whose isOpened() is False - a naive
    start() would report success (a non-None path, is_recording=True) while
    silently producing an empty file. start() must check isOpened() and
    only report success when a codec actually opened."""
    recorder = VideoRecorder(tmp_path, fps=10)
    fake_writer = MagicMock()
    fake_writer.isOpened.return_value = False
    with patch("cv2.VideoWriter", return_value=fake_writer), patch("cv2.VideoWriter_fourcc"):
        path = recorder.start(width=64, height=48)

    assert path is None
    assert recorder.is_recording is False
    # Every fallback codec was tried, not just the first.
    assert fake_writer.isOpened.call_count == len(VideoRecorder._CODEC_FALLBACKS)


def test_write_does_not_block_the_caller_while_the_encoder_is_slow(tmp_path):
    """Real field-reported bug: recording used to make the whole live feed
    "get slow" - traced to write() blocking its caller for the duration of
    a real cv2.VideoWriter.write() call, once per frame. write() must
    return essentially immediately regardless of how long the underlying
    encode actually takes."""
    recorder = VideoRecorder(tmp_path, fps=10)
    slow_writer = MagicMock()
    release_called = threading.Event()

    def slow_write(_frame):
        time.sleep(0.2)

    slow_writer.write.side_effect = slow_write
    slow_writer.isOpened.return_value = True

    def fake_release():
        release_called.set()

    slow_writer.release.side_effect = fake_release

    with patch("cv2.VideoWriter", return_value=slow_writer), patch("cv2.VideoWriter_fourcc"):
        recorder.start(width=64, height=48)
        frame = np.zeros((48, 64, 3), dtype=np.uint8)

        started_at = time.monotonic()
        recorder.write(frame)
        elapsed = time.monotonic() - started_at

        assert elapsed < 0.1  # nowhere near the encoder's own 0.2s
        assert not release_called.is_set()  # the write hasn't even landed yet

        recorder.stop()
        assert release_called.is_set()  # stop() drained the slow write first


def test_stop_waits_for_every_submitted_write_before_releasing(tmp_path):
    """stop() must drain the write queue before finalizing the container -
    releasing while writes are still in flight would drop trailing frames
    or race with the encoder."""
    recorder = VideoRecorder(tmp_path, fps=10)
    recorder.start(width=64, height=48)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    for _ in range(20):
        recorder.write(frame)
    path = recorder.stop()

    assert path is not None
    assert path.stat().st_size > 0


def test_start_falls_back_to_a_working_codec(tmp_path):
    """If the preferred codec (mp4v) fails to open but a later fallback
    (e.g. MJPG) succeeds, start() must use that one rather than giving up."""
    recorder = VideoRecorder(tmp_path, fps=10)
    failing_writer = MagicMock()
    failing_writer.isOpened.return_value = False
    working_writer = MagicMock()
    working_writer.isOpened.return_value = True

    with (
        patch("cv2.VideoWriter", side_effect=[failing_writer, working_writer]),
        patch("cv2.VideoWriter_fourcc"),
    ):
        path = recorder.start(width=64, height=48)

    assert path is not None
    assert path.suffix == ".avi"  # the second fallback (XVID) uses .avi
    assert recorder.is_recording is True
