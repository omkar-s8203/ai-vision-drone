from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any


class MessageType:
    TARGET_SELECT = "target_select"
    MODE_COMMAND = "mode_command"
    ABORT = "abort"
    ARM_COMMAND = "arm_command"
    SET_FLIGHT_MODE = "set_flight_mode"
    RECORD_COMMAND = "record_command"
    RECORDING_STATE = "recording_state"
    LAND_CONFIRMATION_REQUEST = "land_confirmation_request"
    LAND_CONFIRMATION_RESPONSE = "land_confirmation_response"
    TRACKING_UPDATE = "tracking_update"
    DETECTIONS_UPDATE = "detections_update"
    TELEMETRY = "telemetry"
    HEALTH = "health"
    ACK = "ack"
    ERROR = "error"
    WEBRTC_OFFER = "webrtc_offer"
    WEBRTC_ANSWER = "webrtc_answer"


@dataclass
class Envelope:
    type: str
    seq: int
    ts: float
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Envelope":
        data = json.loads(raw)
        return cls(
            type=data["type"], seq=data["seq"], ts=data["ts"], payload=data.get("payload", {})
        )


class SequenceCounter:
    def __init__(self) -> None:
        self._seq = 0

    def next(self) -> int:
        self._seq += 1
        return self._seq


def make_envelope(msg_type: str, payload: dict[str, Any], seq: int) -> Envelope:
    return Envelope(type=msg_type, seq=seq, ts=time.time(), payload=payload)
