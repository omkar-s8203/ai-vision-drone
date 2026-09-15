from __future__ import annotations

from typing import Callable, Optional

from companion.comms.protocol import Envelope, MessageType, SequenceCounter, make_envelope
from companion.comms.transport import Transport


class GroundStationLink:
    """High-level Pi<->Android control/telemetry channel, built on a
    Transport (WebSocketTransport by default). Video is a separate channel
    (video_pipeline.py) so a video hiccup never blocks an abort command.
    """

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self._seq = SequenceCounter()
        self._on_target_selected: Optional[Callable[[dict], None]] = None
        self._on_mode_command: Optional[Callable[[dict], None]] = None
        self._on_abort: Optional[Callable[[dict], None]] = None
        transport.on_message(self._dispatch)

    async def start(self) -> None:
        await self.transport.start()

    async def stop(self) -> None:
        await self.transport.stop()

    def on_target_selected(self, handler: Callable[[dict], None]) -> None:
        self._on_target_selected = handler

    def on_mode_command(self, handler: Callable[[dict], None]) -> None:
        self._on_mode_command = handler

    def on_abort(self, handler: Callable[[dict], None]) -> None:
        self._on_abort = handler

    def _dispatch(self, raw: str) -> None:
        try:
            envelope = Envelope.from_json(raw)
        except Exception:
            return
        if envelope.type == MessageType.TARGET_SELECT and self._on_target_selected:
            self._on_target_selected(envelope.payload)
        elif envelope.type == MessageType.MODE_COMMAND and self._on_mode_command:
            self._on_mode_command(envelope.payload)
        elif envelope.type == MessageType.ABORT and self._on_abort:
            self._on_abort(envelope.payload)

    async def send_tracking_update(self, payload: dict) -> None:
        await self._send(MessageType.TRACKING_UPDATE, payload)

    async def send_telemetry(self, payload: dict) -> None:
        await self._send(MessageType.TELEMETRY, payload)

    async def send_health(self, payload: dict) -> None:
        await self._send(MessageType.HEALTH, payload)

    async def _send(self, msg_type: str, payload: dict) -> None:
        envelope = make_envelope(msg_type, payload, self._seq.next())
        await self.transport.broadcast(envelope.to_json())

    @property
    def is_connected(self) -> bool:
        return getattr(self.transport, "has_clients", False)
