"""Picamera2IMX500Camera's capture runs off the event loop and a stopped
camera is detected. capture_request() used to run on the event loop itself,
so a camera that hung froze the whole process - MAVLink, the operator link,
the failsafes - with nothing to notice.

picamera2 only exists on a Pi, so it is replaced here by fakes whose
capture_request() can deliver, hang or fail on demand."""

import asyncio
import sys
import threading
import types
from unittest.mock import MagicMock, patch

import pytest

from companion.vision import camera as camera_module
from companion.vision.camera import CameraStallError, Picamera2IMX500Camera


class _FakeRequest:
    def __init__(self, n: int) -> None:
        self.n = n
        self.released = False

    def get_metadata(self):
        return {"frame": self.n}

    def make_array(self, _stream):
        return f"pixels-{self.n}"

    def release(self):
        self.released = True


class _FakePicamera2:
    """capture_request() delivers `good_frames` frames, then does `then`:
    "hang" (blocks until released), "fail" (raises) or "more" (keeps going)."""

    instances: list = []

    def __init__(self, _camera_num) -> None:
        self.good_frames = 3
        self.then = "hang"
        self.count = 0
        self.stopped = False
        self.release_hang = threading.Event()
        _FakePicamera2.instances.append(self)

    def create_preview_configuration(self, **_kwargs):
        return {}

    def configure(self, _config):
        pass

    def start(self, show_preview=False):
        pass

    def stop(self):
        self.stopped = True

    def capture_request(self):
        if self.count >= self.good_frames:
            if self.then == "hang":
                self.release_hang.wait()
                raise RuntimeError("released")
            if self.then == "fail":
                raise OSError("V4L2 dequeue failed")
        self.count += 1
        threading.Event().wait(0.005)  # a (very fast) frame period
        return _FakeRequest(self.count)


@pytest.fixture
def fake_picamera2(monkeypatch):
    _FakePicamera2.instances = []
    imx500 = MagicMock()
    imx500.get_outputs.side_effect = lambda metadata, add_batch: [metadata["frame"]]
    picamera2 = types.ModuleType("picamera2")
    picamera2.Picamera2 = _FakePicamera2
    devices = types.ModuleType("picamera2.devices")
    devices.IMX500 = MagicMock(return_value=imx500)
    monkeypatch.setitem(sys.modules, "picamera2", picamera2)
    monkeypatch.setitem(sys.modules, "picamera2.devices", devices)
    monkeypatch.setattr(camera_module, "CAMERA_FIRST_FRAME_TIMEOUT_S", 0.5)
    yield
    for cam in _FakePicamera2.instances:
        cam.release_hang.set()


def _camera(stall_timeout_s=0.2):
    return Picamera2IMX500Camera("/fake.rpk", 640, 480, 30, stall_timeout_s=stall_timeout_s)


def _picam():
    return _FakePicamera2.instances[-1]


@pytest.mark.asyncio
async def test_frames_carry_the_image_and_its_own_ai_output(fake_picamera2):
    camera = _camera()
    frames = camera.frames()
    frame = await asyncio.wait_for(frames.__anext__(), 2.0)
    _imx500, outputs, metadata, _picam2 = frame.raw_detection_output
    assert outputs == [metadata["frame"]]
    assert camera.get_latest_frame() == f"pixels-{metadata['frame']}"
    await frames.aclose()


@pytest.mark.asyncio
async def test_a_hung_camera_raises_camera_stall_error(fake_picamera2):
    camera = _camera(stall_timeout_s=0.2)
    received = 0
    with pytest.raises(CameraStallError, match="no camera frame"):
        async for _frame in camera.frames():
            received += 1
    assert received >= 1


@pytest.mark.asyncio
async def test_a_hung_camera_does_not_freeze_the_event_loop(fake_picamera2):
    """The rest of the process (MAVLink, the operator link) keeps running
    while capture is stuck."""
    camera = _camera(stall_timeout_s=0.5)
    ticks = 0

    async def other_work():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    worker = asyncio.create_task(other_work())
    with pytest.raises(CameraStallError):
        async for _frame in camera.frames():
            pass
    worker.cancel()
    assert ticks >= 20  # it ran throughout the ~0.5s stall


@pytest.mark.asyncio
async def test_a_failing_capture_raises_camera_stall_error(fake_picamera2):
    camera = _camera()
    frames = camera.frames()
    await asyncio.wait_for(frames.__anext__(), 2.0)  # constructs the fake Picamera2
    _picam().then = "fail"
    with pytest.raises(CameraStallError, match="capture failed"):
        while True:
            await asyncio.wait_for(frames.__anext__(), 2.0)


@pytest.mark.asyncio
async def test_the_first_frame_gets_the_longer_startup_allowance(fake_picamera2, monkeypatch):
    monkeypatch.setattr(camera_module, "CAMERA_FIRST_FRAME_TIMEOUT_S", 1.0)
    camera = _camera(stall_timeout_s=0.05)
    frames = camera.frames()
    # Deliver the first frame only after the (much shorter) stall timeout.
    original = _FakePicamera2.capture_request

    def slow_first(self):
        if self.count == 0:
            threading.Event().wait(0.2)
        return original(self)

    with patch.object(_FakePicamera2, "capture_request", slow_first):
        frame = await asyncio.wait_for(frames.__anext__(), 2.0)
    assert frame is not None
    await frames.aclose()


@pytest.mark.asyncio
async def test_closing_normally_stops_the_camera(fake_picamera2):
    camera = _camera()
    frames = camera.frames()
    await asyncio.wait_for(frames.__anext__(), 2.0)
    _picam().then = "more"
    await frames.aclose()
    assert _picam().stopped


@pytest.mark.asyncio
async def test_a_hung_capture_thread_is_not_waited_on_by_stop(fake_picamera2):
    """picam2.stop() would block on the same hung request - it is skipped and
    left to the process exit."""
    camera = _camera(stall_timeout_s=0.1)
    with pytest.raises(CameraStallError):
        async for _frame in camera.frames():
            pass
    assert not _picam().stopped


@pytest.mark.asyncio
async def test_the_capture_thread_is_a_daemon(fake_picamera2):
    """A hung capture thread must not keep the process alive for systemd's restart."""
    camera = _camera()
    frames = camera.frames()
    await asyncio.wait_for(frames.__anext__(), 2.0)
    capture = [t for t in threading.enumerate() if t.name == "camera-capture"]
    assert capture and all(t.daemon for t in capture)
    _picam().then = "more"
    await frames.aclose()
