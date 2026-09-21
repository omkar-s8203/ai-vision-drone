"""Tests for companion/guidance/rangefinder.py's Benewake TFmini-S driver.

distance_m_from_frame() is pure and tested directly against synthetic
byte frames. TFMiniRangefinderSource is tested against a fake serial port
(duck-typed: .in_waiting + .read(n)) rather than pyserial or real
hardware - nobody has wired an actual TFmini-S to a real Pi UART for this
project yet (see the module's own docstring).
"""

from companion.guidance.rangefinder import (
    FRAME_LENGTH,
    HEADER_BYTE,
    MAX_DISTANCE_CM,
    MIN_DISTANCE_CM,
    MIN_SIGNAL_STRENGTH,
    TFMiniRangefinderSource,
    distance_m_from_frame,
)


def make_frame(distance_cm: int, strength: int, reserved: bytes = b"\x00\x00") -> bytes:
    body = bytes(
        [
            HEADER_BYTE,
            HEADER_BYTE,
            distance_cm & 0xFF,
            (distance_cm >> 8) & 0xFF,
            strength & 0xFF,
            (strength >> 8) & 0xFF,
        ]
    ) + reserved
    checksum = sum(body) & 0xFF
    return body + bytes([checksum])


class FakePort:
    """Duck-types pyserial's Serial interface: .in_waiting + .read(n)."""

    def __init__(self, data: bytes) -> None:
        self._buf = data

    @property
    def in_waiting(self) -> int:
        return len(self._buf)

    def read(self, size: int = 1) -> bytes:
        chunk = self._buf[:size]
        self._buf = self._buf[size:]
        return chunk


def test_distance_m_from_frame_parses_a_valid_frame():
    frame = make_frame(distance_cm=350, strength=500)
    assert distance_m_from_frame(frame) == 3.5


def test_distance_m_from_frame_rejects_a_bad_checksum():
    frame = bytearray(make_frame(distance_cm=350, strength=500))
    frame[-1] ^= 0xFF  # corrupt the checksum byte
    assert distance_m_from_frame(bytes(frame)) is None


def test_distance_m_from_frame_rejects_low_signal_strength():
    frame = make_frame(distance_cm=350, strength=MIN_SIGNAL_STRENGTH - 1)
    assert distance_m_from_frame(frame) is None


def test_distance_m_from_frame_accepts_strength_at_the_floor():
    frame = make_frame(distance_cm=350, strength=MIN_SIGNAL_STRENGTH)
    assert distance_m_from_frame(frame) == 3.5


def test_distance_m_from_frame_rejects_distance_below_rated_range():
    frame = make_frame(distance_cm=MIN_DISTANCE_CM - 1, strength=500)
    assert distance_m_from_frame(frame) is None


def test_distance_m_from_frame_rejects_distance_above_rated_range():
    frame = make_frame(distance_cm=MAX_DISTANCE_CM + 1, strength=500)
    assert distance_m_from_frame(frame) is None


def test_source_reads_a_single_buffered_frame():
    port = FakePort(make_frame(distance_cm=200, strength=500))
    source = TFMiniRangefinderSource(port)
    assert source.read() == 2.0


def test_source_returns_the_most_recently_buffered_frame_not_a_stale_one():
    data = make_frame(distance_cm=100, strength=500) + make_frame(distance_cm=999, strength=500)
    port = FakePort(data)
    source = TFMiniRangefinderSource(port)
    assert source.read() == 9.99


def test_source_resyncs_past_garbage_bytes_before_a_valid_frame():
    """A dropped/corrupted byte on a real UART line shouldn't be treated as
    a fatal error - the driver should find the next real frame instead."""
    garbage = bytes([0x00, 0x12, HEADER_BYTE, 0x34])
    data = garbage + make_frame(distance_cm=150, strength=500)
    port = FakePort(data)
    source = TFMiniRangefinderSource(port)
    assert source.read() == 1.5


def test_source_returns_none_when_fewer_bytes_than_a_full_frame_are_buffered():
    port = FakePort(bytes([HEADER_BYTE, HEADER_BYTE, 0x01]))
    assert len(port._buf) < FRAME_LENGTH
    source = TFMiniRangefinderSource(port)
    assert source.read() is None


def test_source_returns_none_when_nothing_valid_is_buffered():
    port = FakePort(bytes([0x00] * 20))
    source = TFMiniRangefinderSource(port)
    assert source.read() is None
