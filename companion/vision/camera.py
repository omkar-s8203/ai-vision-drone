from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional


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


class Picamera2IMX500Camera(CameraBase):
    """Real hardware camera backend - Raspberry Pi AI Camera (Sony IMX500).

    Only importable/usable on a Raspberry Pi with picamera2 + the imx500
    stack installed. Detection runs on-sensor; this class just pulls frames
    and their attached inference metadata.

    Confirmed against real hardware (not guessed): `picamera2.devices.IMX500`
    is constructed from the .rpk model path and owns `camera_num`; frames
    come from `Picamera2.capture_metadata()` (not `capture_request()`), and
    `IMX500.get_outputs(metadata, add_batch=True)` returns the raw tensor
    list - or None on frames before the on-sensor network has produced its
    first result (normal for the first ~second after start()). Coordinate
    conversion needs both `metadata` and the `Picamera2` instance, so all
    three (imx500, outputs, metadata, picam2) are bundled into
    `raw_detection_output` for IMX500Detector to unpack.
    """

    def __init__(self, model_path: str, width: int, height: int, target_fps: int) -> None:
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
        self._picam2.start(config, show_preview=False)
        try:
            period = 1.0 / self.target_fps
            while True:
                metadata = self._picam2.capture_metadata()
                outputs = self.imx500.get_outputs(metadata, add_batch=True)
                self.last_frame_array = self._picam2.capture_array("main")
                yield Frame(
                    ts=time.monotonic(),
                    width=self.width,
                    height=self.height,
                    raw_detection_output=(self.imx500, outputs, metadata, self._picam2),
                )
                await asyncio.sleep(period)
        finally:
            self._picam2.stop()


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
        while True:
            ts = time.monotonic() - start
            yield Frame(
                ts=ts,
                width=self.width,
                height=self.height,
                raw_detection_output=self.detection_source(ts),
            )
            await asyncio.sleep(period)
