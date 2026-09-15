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
    """

    def __init__(self, width: int, height: int, target_fps: int) -> None:
        try:
            from picamera2 import Picamera2  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "picamera2 is not available - Picamera2IMX500Camera only runs on a "
                "Raspberry Pi with the imx500 camera stack installed. Use SyntheticCamera "
                "for development/simulation."
            ) from exc
        self._Picamera2 = Picamera2
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self._picam2 = None

    async def frames(self) -> AsyncIterator[Frame]:
        self._picam2 = self._Picamera2()
        config = self._picam2.create_video_configuration(
            main={"size": (self.width, self.height)}
        )
        self._picam2.configure(config)
        self._picam2.start()
        try:
            period = 1.0 / self.target_fps
            while True:
                request = self._picam2.capture_request()
                try:
                    metadata = request.get_metadata()
                finally:
                    request.release()
                yield Frame(
                    ts=time.monotonic(),
                    width=self.width,
                    height=self.height,
                    raw_detection_output=metadata,
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
