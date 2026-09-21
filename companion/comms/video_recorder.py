from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional


class VideoRecorder:
    """Writes camera frames to an MP4 file on the Pi's own storage, so
    footage is captured locally regardless of network/streaming conditions
    (unlike the WebRTC feed, which can drop or degrade with WiFi range).
    Only meaningful with a real frame source (hardware mode) - a backend
    with no real image data (SyntheticCamera) is simply never asked to
    record.

    A real field-reported bug ("video gets slow when recording starts, and
    the screen gets stuck when recording stops") turned out to be exactly
    the same class of bug already fixed once this project for
    SessionRecorder: write()'s `cv2.VideoWriter.write()` call is a blocking
    encode+disk-I/O operation, and `CompanionOrchestrator.process_frame()`
    used to `await` it (via `run_in_executor`) inline, once per frame,
    before doing anything else that frame - MAVLink parsing, detection,
    and the WebRTC frame delivery loop all effectively ran at whatever rate
    `cv2.VideoWriter.write()` could keep up with, not the camera's own
    frame rate. Wrapping the call in `run_in_executor` only kept it from
    blocking the whole *event loop* for other, unrelated tasks - it did
    nothing to stop it from blocking *this* coroutine, which is the one
    actually producing frames for the live feed. write() now submits to a
    dedicated single-worker thread pool instead and returns immediately,
    the same fix already applied to SessionRecorder.record() - the caller
    no longer needs (and must not use) run_in_executor around it.

    stop()'s `cv2.VideoWriter.release()` is a separate, one-time blocking
    call (finalizing the container, e.g. writing an MP4's moov atom) - a
    real block on the shared event loop for its duration, which showed up
    as the live video "getting stuck" for however long release() took.
    Unlike write(), this one call happens once per recording, not once per
    frame, so `CompanionOrchestrator._handle_record_command` (a separate
    task from the per-frame loop, not the hot path) offloading start()/
    stop() themselves via `run_in_executor` is the correct fix here -
    genuinely non-blocking, since this isn't the call gating how fast the
    next frame can be produced.
    """

    def __init__(self, output_dir: Path, fps: int) -> None:
        self.output_dir = output_dir
        self.fps = fps
        self._writer = None
        self._path: Optional[Path] = None
        self._started_ts: Optional[float] = None
        self._executor: Optional[ThreadPoolExecutor] = None

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    @property
    def current_path(self) -> Optional[Path]:
        return self._path

    @property
    def duration_s(self) -> float:
        if self._started_ts is None:
            return 0.0
        return time.monotonic() - self._started_ts

    # Tried in order - mp4v is preferred (plays natively almost everywhere),
    # but some OpenCV builds (particularly headless pip wheels on ARM) lack
    # the codec support to actually open it despite not raising - a real bug
    # found in the field: cv2.VideoWriter() never throws on failure, it just
    # returns a writer whose isOpened() is False, so every write() silently
    # no-ops and you end up with an empty file and no error anywhere. MJPG
    # in an .avi container is close to universally supported as a last resort.
    _CODEC_FALLBACKS = (("mp4v", "mp4"), ("XVID", "avi"), ("MJPG", "avi"))

    def start(self, width: int, height: int) -> Optional[Path]:
        """Returns the recording's path, or None if every codec fallback
        failed to open - callers must check for None rather than assuming
        a non-raising call means recording actually started."""
        if self.is_recording:
            return self._path  # already recording - idempotent, not an error
        import cv2  # lazy import: only needed if recording is actually used

        self.output_dir.mkdir(parents=True, exist_ok=True)
        for fourcc_str, extension in self._CODEC_FALLBACKS:
            path = self.output_dir / f"recording_{int(time.time())}.{extension}"
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            writer = cv2.VideoWriter(str(path), fourcc, self.fps, (width, height))
            if writer.isOpened():
                self._writer = writer
                self._path = path
                self._started_ts = time.monotonic()
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-recorder")
                return path
            writer.release()
        return None

    def write(self, frame_bgr) -> None:
        """Non-blocking: submits the actual encode+disk-I/O to a dedicated
        worker thread and returns immediately - see the class docstring for
        the real "video gets slow while recording" bug this fixes. The
        single worker preserves write order (submissions are processed
        FIFO, same as writing inline would have been)."""
        if self._writer is not None and frame_bgr is not None and self._executor is not None:
            self._executor.submit(self._writer.write, frame_bgr)

    def stop(self) -> Optional[Path]:
        if self._writer is None:
            return None
        if self._executor is not None:
            # Drain every already-submitted write before finalizing the
            # container - releasing while writes are still queued would
            # either drop trailing frames or race with the encoder.
            self._executor.shutdown(wait=True)
            self._executor = None
        self._writer.release()
        self._writer = None
        self._started_ts = None
        path = self._path
        self._path = None
        return path
