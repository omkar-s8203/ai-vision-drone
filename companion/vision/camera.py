from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

log = logging.getLogger(__name__)

# Default for hardware.yaml's camera.stall_timeout_s: no frame for this long
# after the first one means the camera has stopped (see Picamera2IMX500Camera).
DEFAULT_CAMERA_STALL_TIMEOUT_S = 2.0
# The first frame gets longer - the sensor's AI firmware may still be loading.
CAMERA_FIRST_FRAME_TIMEOUT_S = 15.0


class CameraStallError(RuntimeError):
    """The camera stopped delivering frames (capture hung or failed). Not
    recoverable in-process - a hung libcamera request cannot be cancelled -
    so the orchestrator exits and systemd restarts the service."""


@dataclass
class Frame:
    ts: float
    width: int
    height: int
    raw_detection_output: object  # backend-specific, consumed by a matching DetectorBase


class CameraBase:
    async def frames(self) -> AsyncIterator[Frame]:
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for type checkers

    def get_latest_frame(self):
        """Optional: returns the most recent captured image array (BGR
        uint8), or None if this backend doesn't expose one (e.g.
        SyntheticCamera has no real image data). Used by the video pipeline
        and video recorder, both of which need actual pixels, not just
        detection metadata."""
        return None


class Picamera2IMX500Camera(CameraBase):
    """Real hardware camera backend - Raspberry Pi AI Camera (Sony IMX500).

    Only importable/usable on a Raspberry Pi with picamera2 + the imx500
    stack installed. Detection runs on-sensor; this class just pulls frames
    and their attached inference metadata.

    Confirmed against real hardware (not guessed): `picamera2.devices.IMX500`
    is constructed from the .rpk model path and owns `camera_num`; frames
    come from a single `Picamera2.capture_request()` per iteration (see the
    real bug below for why this matters), and
    `IMX500.get_outputs(metadata, add_batch=True)` returns the raw tensor
    list - or None on frames before the on-sensor network has produced its
    first result (normal for the first ~second after start()). Coordinate
    conversion needs both `metadata` and the `Picamera2` instance, so all
    three (imx500, outputs, metadata, picam2) are bundled into
    `raw_detection_output` for IMX500Detector to unpack.

    A real bug found from a field log (not a demo script), root-caused
    across three passes - each one only fully understood once a standalone
    diagnostic script (independent of this class, run directly on the Pi)
    proved or disproved it against real hardware:

    1. `outputs` was None on every frame indefinitely, not just the normal
       ~1s startup grace period. Hypothesis: the on-sensor network's
       firmware upload to the NPU (a separate, async step from opening the
       camera) was never being waited on. Fix: call
       `IMX500.show_network_fw_progress_bar()`.
    2. That fix, deployed and re-tested against real hardware, did not
       help. A diagnostic script proved the call was placed before
       `configure()` had ever run, so there was nothing to wait for yet -
       reordered to `configure()` -> `show_network_fw_progress_bar()` ->
       `start()`.
    3. Even with that reordering fixed, a genuinely cold-boot diagnostic
       run showed the firmware upload completing at 100% (confirmed by its
       own progress bar) within ~3s, but `get_outputs()` still never
       returned real results for 60s straight afterward. The actual
       culprit: this class previously called `capture_metadata()` and
       `capture_array("main")` as two separate, independently-triggered
       captures per loop iteration - a diagnostic script proved this
       combination desyncs which underlying frame's metadata you actually
       get vs. which frame's image you captured, so `get_outputs()` never
       lines up with a frame that has real inference attached. Switching
       to a single `capture_request()` per iteration - guaranteeing the
       metadata and the image array both come from the exact same
       underlying frame - fixed it: real output at frame 2 (~3s, exactly
       matching firmware upload completion) in that diagnostic script.
    """

    def __init__(
        self,
        model_path: str,
        width: int,
        height: int,
        target_fps: int,
        stall_timeout_s: float = DEFAULT_CAMERA_STALL_TIMEOUT_S,
    ) -> None:
        try:
            from picamera2 import Picamera2  # type: ignore
            from picamera2.devices import IMX500  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "picamera2 is not available - Picamera2IMX500Camera only runs on a "
                "Raspberry Pi with the imx500 camera stack installed. Use SyntheticCamera "
                "for development/simulation."
            ) from exc
        self.imx500 = IMX500(model_path)
        self._Picamera2 = Picamera2
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.stall_timeout_s = stall_timeout_s
        self._picam2 = None
        self.last_frame_array = None  # BGR uint8 array, for the video pipeline's frame_source

    def get_latest_frame(self):
        """Synchronous accessor for the most recent captured image - used as
        the video pipeline's frame_source callback, which runs outside this
        class's own async frame loop (docs plan M5/M6 hardware wiring)."""
        return self.last_frame_array

    async def frames(self) -> AsyncIterator[Frame]:
        self._picam2 = self._Picamera2(self.imx500.camera_num)
        config = self._picam2.create_preview_configuration(
            # picamera2's format names are inverted relative to the actual
            # numpy channel order they produce: requesting "RGB888" here is
            # what actually yields BGR-ordered array data, matching what
            # AiortcVideoPipeline passes to PyAV as "bgr24". Confirmed
            # against real hardware - requesting "BGR888" produced a
            # visibly wrong (red/blue swapped) video feed.
            main={"size": (self.width, self.height), "format": "RGB888"},
            controls={"FrameRate": self.target_fps},
            buffer_count=12,
        )
        # A real bug found in the field: outputs=None forever, not just the
        # normal ~1s startup grace period - the on-sensor network's firmware
        # upload to the NPU is a separate, asynchronous step from starting
        # the camera, and nothing was waiting for it to finish before capture
        # began. The first fix attempt called show_network_fw_progress_bar()
        # here, before configure() had ever run - confirmed by a standalone
        # diagnostic script to be too early: the upload hadn't started yet
        # (get_fw_upload_progress() read (0, 0)), so the "wait" returned
        # instantly and did nothing. The upload only actually begins once
        # the camera is configured, so configure() must happen first, then
        # the wait, then start() (with no config argument - already
        # configured) - the same diagnostic script confirmed this exact
        # order produces a real detection within ~3s. Guarded with hasattr()
        # since this dev machine has no picamera2/IMX500 to confirm the
        # exact method name against every version - if a future version
        # renames or removes it, fail loud in the log rather than silently
        # regressing to outputs=None with no clue why.
        self._picam2.configure(config)
        if hasattr(self.imx500, "show_network_fw_progress_bar"):
            self.imx500.show_network_fw_progress_bar()
        else:
            log.warning(
                "IMX500.show_network_fw_progress_bar() not found on this picamera2 version - "
                "the network firmware upload may not be awaited before capture starts, which "
                "previously caused IMX500Detector to see outputs=None indefinitely"
            )
        self._picam2.start(show_preview=False)
        captured = self._captured_frames()
        try:
            async for frame in captured:
                yield frame
        finally:
            await captured.aclose()  # stops the capture thread and the camera now, not at GC

    def _capture_one(self):
        """One frame, on the capture thread. capture_request() blocks until the
        next frame is ready at the hardware FrameRate configured above - it IS
        the pacing mechanism. A real bug found in the field: the loop used to
        also `await asyncio.sleep(1.0 / target_fps)` after every frame, adding a
        second full frame period and roughly halving throughput (a configured
        30 FPS delivered ~15). Do not add a sleep back.

        Deliberately ONE capture_request() per frame, not separate
        capture_metadata() + capture_array() calls - see the class docstring's
        bug #3. Each of those triggers its own independent capture, and
        get_outputs() needs the exact same underlying frame's metadata that its
        image came from; requesting them separately let those desync and left
        get_outputs() permanently None on real hardware."""
        request = self._picam2.capture_request()
        try:
            metadata = request.get_metadata()
            array = request.make_array("main")
            outputs = self.imx500.get_outputs(metadata, add_batch=True)
        finally:
            request.release()
        return time.monotonic(), array, outputs, metadata

    async def _captured_frames(self) -> AsyncIterator[Frame]:
        """Capture runs on its own daemon thread. It used to run right here on
        the event loop, so a camera that hung inside capture_request() froze the
        whole process - MAVLink, the operator link, the failsafes - with nothing
        to notice. Now a missing frame is detected after stall_timeout_s and
        raised as CameraStallError. The thread is a daemon because a hung
        libcamera call cannot be interrupted, and must not keep the process
        alive for systemd's restart."""
        loop = asyncio.get_running_loop()
        latest: asyncio.Queue = asyncio.Queue(maxsize=1)
        stop = threading.Event()

        def publish(item) -> None:  # on the event loop
            if latest.full():
                latest.get_nowait()  # the loop fell behind: newest frame wins
            latest.put_nowait(item)

        def capture_loop() -> None:  # on the capture thread
            while not stop.is_set():
                try:
                    item = self._capture_one()
                except Exception as exc:
                    item = exc
                try:
                    loop.call_soon_threadsafe(publish, item)
                except RuntimeError:
                    return  # the event loop is gone
                if isinstance(item, Exception):
                    return

        thread = threading.Thread(target=capture_loop, name="camera-capture", daemon=True)
        thread.start()
        timeout_s = max(self.stall_timeout_s, CAMERA_FIRST_FRAME_TIMEOUT_S)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(latest.get(), timeout_s)
                except asyncio.TimeoutError:
                    raise CameraStallError(f"no camera frame for {timeout_s:.1f}s") from None
                if isinstance(item, Exception):
                    raise CameraStallError(f"camera capture failed: {item}") from item
                ts, array, outputs, metadata = item
                self.last_frame_array = array
                yield Frame(
                    ts=ts,
                    width=self.width,
                    height=self.height,
                    raw_detection_output=(self.imx500, outputs, metadata, self._picam2),
                )
                timeout_s = self.stall_timeout_s
        finally:
            stop.set()
            thread.join(timeout=self.stall_timeout_s)
            if thread.is_alive():
                # stop() would wait on the same hung request - leave it to the
                # process exit.
                log.error("Camera capture thread is hung - not stopping the camera")
            else:
                self._picam2.stop()


def open_real_camera_and_detector(hardware_cfg: dict):
    """Constructs the real Picamera2IMX500Camera + IMX500Detector from a
    loaded hardware.yaml - shared by tools/benchmark_detection.py and
    tools/detection_regression.py so they don't each duplicate this (the
    same construction companion/main.py's build_hardware_orchestrator()
    also does, kept separate there rather than refactored to share this,
    to avoid touching already-deployed, working production wiring for a
    tooling change).

    A real field report hit exactly this: `Picamera2IMX500Camera(...)`
    raising a bare `OSError: [Errno 16] Device or resource busy` deep
    inside picamera2/V4L2, with no indication of *why*. The camera device
    can only be held open by one process at a time, and the far more
    likely cause than the raw message suggests is that the
    `ai-vision-drone` systemd service (companion.main) is already running
    and holding it - re-raised here as a clear, actionable message instead
    of a bare traceback.
    """
    from companion.vision.detector import IMX500Detector

    try:
        camera = Picamera2IMX500Camera(
            model_path=hardware_cfg["camera"]["imx500_model_path"],
            width=hardware_cfg["camera"]["width"],
            height=hardware_cfg["camera"]["height"],
            target_fps=hardware_cfg["camera"]["target_fps"],
        )
    except (RuntimeError, OSError) as exc:
        if "busy" in str(exc).lower():
            raise RuntimeError(
                "The camera device is already open by another process - most likely the "
                "ai-vision-drone systemd service (companion.main) is already running and "
                "holding it. Stop it first, then retry:\n"
                "    sudo systemctl stop ai-vision-drone\n"
                "Restart it afterward once you're done (it normally auto-starts on boot):\n"
                "    sudo systemctl start ai-vision-drone"
            ) from exc
        raise
    detector = IMX500Detector(
        class_names=camera.imx500.network_intrinsics.labels,
        score_threshold=hardware_cfg["camera"].get("score_threshold", 0.5),
    )
    return camera, detector


class SyntheticCamera(CameraBase):
    """Sim/dev camera backend - no real image data, just a frame clock.

    A `detection_source` callback is called once per frame to produce the
    raw detection payload for that timestamp (see sim/synthetic_target.py).
    Lets the whole tracking/guidance/safety pipeline be exercised without
    any real camera or Pi hardware.
    """

    def __init__(
        self,
        width: int,
        height: int,
        target_fps: int,
        detection_source: Optional[Callable[[float], object]] = None,
    ) -> None:
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.detection_source = detection_source or (lambda _ts: [])

    async def frames(self) -> AsyncIterator[Frame]:
        period = 1.0 / self.target_fps
        start = time.monotonic()
        next_frame_at = start
        while True:
            ts = time.monotonic() - start
            yield Frame(
                ts=ts,
                width=self.width,
                height=self.height,
                raw_detection_output=self.detection_source(ts),
            )
            # Fixed-rate (not fixed-delay) scheduling: advance the target by
            # exactly one period rather than sleeping a full period after
            # whatever this iteration's own work already cost, so per-frame
            # overhead doesn't compound into a lower actual rate than
            # target_fps (see Picamera2IMX500Camera.frames() for the real
            # version of this bug found on hardware).
            next_frame_at += period
            sleep_s = next_frame_at - time.monotonic()
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            else:
                next_frame_at = time.monotonic()
