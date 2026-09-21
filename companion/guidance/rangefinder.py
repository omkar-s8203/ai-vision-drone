from __future__ import annotations

from typing import Optional, Protocol

from companion.guidance.distance import DistanceSource

# Benewake TFmini-S: the specific sensor picked for this project's M4
# rangefinder addition (plan's own suggested price range, ~$25, and its UART
# protocol is public and stable - used by many open drone/robotics projects,
# including ArduPilot's own AP_RangeFinder_Benewake driver). Frame format
# per Benewake's published TFmini-S product manual: a continuous stream of
# 9-byte frames at the default 115200 baud, 8N1, ~100Hz:
#   byte 0-1: header, 0x59 0x59
#   byte 2-3: distance, cm, uint16 little-endian
#   byte 4-5: signal strength, uint16 little-endian
#   byte 6-7: reserved (raw temperature on some firmware revisions)
#   byte 8:   checksum = (sum of bytes 0-7) & 0xFF
FRAME_LENGTH = 9
HEADER_BYTE = 0x59

# Benewake's own documented "low confidence" floor - below this, the
# reported distance is unreliable (weak/saturated return) and should be
# treated the same as no reading at all, not trusted at face value.
MIN_SIGNAL_STRENGTH = 100

# TFmini-S's own rated range (0.1m-12m); readings outside this aren't
# physically meaningful for this sensor.
MIN_DISTANCE_CM = 10
MAX_DISTANCE_CM = 1200


def _checksum_ok(frame: bytes) -> bool:
    return len(frame) == FRAME_LENGTH and (sum(frame[:8]) & 0xFF) == frame[8]


def distance_m_from_frame(frame: bytes) -> Optional[float]:
    """Parses one already-validated 9-byte TFmini-S frame into a distance
    in meters, or None if the checksum fails, the signal strength is below
    Benewake's own reliability floor, or the distance is outside the
    sensor's rated range. Pure function, deliberately decoupled from any
    real serial I/O so the protocol parsing itself is unit-testable without
    pyserial or real hardware attached."""
    if not _checksum_ok(frame):
        return None
    distance_cm = frame[2] | (frame[3] << 8)
    strength = frame[4] | (frame[5] << 8)
    if strength < MIN_SIGNAL_STRENGTH:
        return None
    if not (MIN_DISTANCE_CM <= distance_cm <= MAX_DISTANCE_CM):
        return None
    return distance_cm / 100.0


class SerialPort(Protocol):
    """The minimal subset of pyserial's Serial interface this driver
    actually needs - accepting this instead of a concrete pyserial type
    lets tests substitute a fake port with synthetic byte frames."""

    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int = 1) -> bytes: ...


class TFMiniRangefinderSource(DistanceSource):
    """Real UART driver for a Benewake TFmini-S, the sensor picked for this
    project's M4 rangefinder addition (see hardware.yaml / root README).
    Not yet confirmed against real hardware - the frame protocol is public
    and stable, and the parsing logic is unit-tested against synthetic
    frames, but nobody has wired an actual TFmini-S to a real Pi UART for
    this project yet.

    Takes an already-open serial-like port rather than a device path so the
    parsing/resync logic can be unit-tested without pyserial or real
    hardware - use `TFMiniRangefinderSource.open()` to build one from a
    real device path.
    """

    def __init__(self, serial_port: SerialPort) -> None:
        self._port = serial_port

    @classmethod
    def open(cls, port: str, baud: int = 115200, timeout_s: float = 0.05) -> "TFMiniRangefinderSource":
        import serial  # pyserial - already a core dependency (pymavlink needs it too)

        return cls(serial.Serial(port, baudrate=baud, timeout=timeout_s))

    def read(self) -> Optional[float]:
        frame = self._read_latest_frame()
        if frame is None:
            return None
        return distance_m_from_frame(frame)

    def _read_latest_frame(self) -> Optional[bytes]:
        """Drains every complete frame currently buffered and returns only
        the most recent valid one - the TFmini-S streams continuously at
        ~100Hz regardless of how often this is called, so anything queued
        up is already stale by the time a caller asks for "the" distance.
        Resyncs on a single stray/misaligned byte rather than treating it
        as a fatal error, since a byte can be dropped or corrupted on a
        real UART line without the stream itself failing.
        """
        latest: Optional[bytes] = None
        while self._port.in_waiting >= FRAME_LENGTH:
            first = self._port.read(1)
            if not first or first[0] != HEADER_BYTE:
                continue
            second = self._port.read(1)
            if not second or second[0] != HEADER_BYTE:
                continue
            rest = self._port.read(FRAME_LENGTH - 2)
            if len(rest) != FRAME_LENGTH - 2:
                break
            frame = bytes([HEADER_BYTE, HEADER_BYTE]) + rest
            if _checksum_ok(frame):
                latest = frame
        return latest
