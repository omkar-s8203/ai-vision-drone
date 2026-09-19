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
        self._handlers: dict[str, Callable[[dict], None]] = {}
        transport.on_message(self._dispatch)

    async def start(self) -> None:
        await self.transport.start()

    async def stop(self) -> None:
        await self.transport.stop()

    def on_target_selected(self, handler: Callable[[dict], None]) -> None:
        self._handlers[MessageType.TARGET_SELECT] = handler

    def on_mode_command(self, handler: Callable[[dict], None]) -> None:
        self._handlers[MessageType.MODE_COMMAND] = handler

    def on_abort(self, handler: Callable[[dict], None]) -> None:
        self._handlers[MessageType.ABORT] = handler

    def on_arm_command(self, handler: Callable[[dict], None]) -> None:
        """handler receives {"armed": bool}."""
        self._handlers[MessageType.ARM_COMMAND] = handler

    def on_set_flight_mode(self, handler: Callable[[dict], None]) -> None:
        """handler receives {"mode": str} - an ArduCopter mode name."""
        self._handlers[MessageType.SET_FLIGHT_MODE] = handler

    def on_record_command(self, handler: Callable[[dict], None]) -> None:
        """handler receives {"recording": bool}."""
        self._handlers[MessageType.RECORD_COMMAND] = handler

    def on_land_confirmation_response(self, handler: Callable[[dict], None]) -> None:
        """handler receives {"approved": bool} - the operator's answer to a
        land_confirmation_request (target-loss recovery, see
        companion/guidance/target_recovery.py)."""
        self._handlers[MessageType.LAND_CONFIRMATION_RESPONSE] = handler

    def on_webrtc_offer(self, handler: Callable[[dict], None]) -> None:
        """handler receives {"sdp": ..., "sdp_type": ...} and is responsible
        for calling send_webrtc_answer() with the resulting answer."""
        self._handlers[MessageType.WEBRTC_OFFER] = handler

    def _dispatch(self, raw: str) -> None:
        try:
            envelope = Envelope.from_json(raw)
        except Exception:
            return
        handler = self._handlers.get(envelope.type)
        if handler is not None:
            handler(envelope.payload)

    async def send_webrtc_answer(self, sdp: str, sdp_type: str) -> None:
        await self._send(MessageType.WEBRTC_ANSWER, {"sdp": sdp, "sdp_type": sdp_type})

    async def send_tracking_update(self, payload: dict) -> None:
        await self._send(MessageType.TRACKING_UPDATE, payload)

    async def send_detections_update(self, payload: dict) -> None:
        await self._send(MessageType.DETECTIONS_UPDATE, payload)

    async def send_telemetry(self, payload: dict) -> None:
        await self._send(MessageType.TELEMETRY, payload)

    async def send_health(self, payload: dict) -> None:
        await self._send(MessageType.HEALTH, payload)

    async def send_recording_state(self, payload: dict) -> None:
        await self._send(MessageType.RECORDING_STATE, payload)

    async def send_land_confirmation_request(self, payload: dict) -> None:
        await self._send(MessageType.LAND_CONFIRMATION_REQUEST, payload)

    async def _send(self, msg_type: str, payload: dict) -> None:
        envelope = make_envelope(msg_type, payload, self._seq.next())
        await self.transport.broadcast(envelope.to_json())

    @property
    def is_connected(self) -> bool:
        return getattr(self.transport, "has_clients", False)
