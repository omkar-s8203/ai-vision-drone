from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from companion.comms.protocol import Envelope, MessageType, SequenceCounter, make_envelope
from companion.comms.transport import Transport

log = logging.getLogger(__name__)


class GroundStationLink:
    """High-level Pi<->Android control/telemetry channel, built on a
    Transport (WebSocketTransport by default). Video is a separate channel
    (video_pipeline.py) so a video hiccup never blocks an abort command.
    """

    def __init__(self, transport: Transport, comms_timeout_s: Optional[float] = None) -> None:
        self.transport = transport
        # None = judge liveness by the socket alone (tests, fake transports).
        # Production builders pass network.yaml's comms_timeout_s.
        self.comms_timeout_s = comms_timeout_s
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

    def on_teach_object(self, handler: Callable[[dict], None]) -> None:
        """handler receives {x, y, w, h, name, real_width_m?, real_height_m?} - the
        operator's drawn box around an object to teach (docs/teach-and-train.md)."""
        self._handlers[MessageType.TEACH_OBJECT] = handler

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
        if envelope.type == MessageType.PING:
            # Answered here, not exposed as an app-level handler: this is a
            # transport-level latency probe (docs plan M5's "WS control
            # round-trip < 50ms" metric), not guidance logic. Echoes the
            # client's own payload back untouched so it can carry whatever
            # client-side timestamp/nonce the caller wants round-tripped.
            asyncio.create_task(self._send(MessageType.PONG, envelope.payload))
            return
        handler = self._handlers.get(envelope.type)
        if handler is not None:
            # A real robustness gap: an unexpected/malformed payload (a
            # missing key, a value that won't cast to float, ...) raising
            # here used to propagate straight out of this synchronous
            # dispatch call, up through WebSocketTransport's `async for raw
            # in ws:` loop - closing the *entire* connection over one bad
            # message, forcing the Android app to notice and reconnect
            # (recoverable, but disruptive and easy to trigger from a
            # single stray field). One handler's bug should drop that one
            # message, not the link.
            try:
                handler(envelope.payload)
            except Exception:
                log.exception("Handler for %r raised on payload %r - message dropped, link stays up", envelope.type, envelope.payload)

    async def send_webrtc_answer(self, sdp: str, sdp_type: str) -> None:
        await self._send(MessageType.WEBRTC_ANSWER, {"sdp": sdp, "sdp_type": sdp_type})

    async def send_tracking_update(self, payload: dict) -> None:
        await self._send(MessageType.TRACKING_UPDATE, payload)

    async def send_detections_update(self, payload: dict) -> None:
        await self._send(MessageType.DETECTIONS_UPDATE, payload)

    async def send_grid_search_update(self, payload: dict) -> None:
        await self._send(MessageType.GRID_SEARCH_UPDATE, payload)

    async def send_telemetry(self, payload: dict) -> None:
        await self._send(MessageType.TELEMETRY, payload)

    async def send_health(self, payload: dict) -> None:
        await self._send(MessageType.HEALTH, payload)

    async def send_recording_state(self, payload: dict) -> None:
        await self._send(MessageType.RECORDING_STATE, payload)

    async def send_land_confirmation_request(self, payload: dict) -> None:
        await self._send(MessageType.LAND_CONFIRMATION_REQUEST, payload)

    async def send_arm_command_result(self, payload: dict) -> None:
        await self._send(MessageType.ARM_COMMAND_RESULT, payload)

    async def send_teach_result(self, payload: dict) -> None:
        await self._send(MessageType.TEACH_RESULT, payload)

    async def _send(self, msg_type: str, payload: dict) -> None:
        envelope = make_envelope(msg_type, payload, self._seq.next())
        await self.transport.broadcast(envelope.to_json())

    @property
    def is_connected(self) -> bool:
        """A client is connected AND has actually been heard from recently.
        Socket state alone is not enough: a dropped WiFi link leaves the TCP
        connection looking open for a long time, during which the operator
        can neither see telemetry nor reach the abort button."""
        if not getattr(self.transport, "has_clients", False):
            return False
        if self.comms_timeout_s is None:
            return True
        age = getattr(self.transport, "seconds_since_last_message", None)
        if age is None:
            return True
        return age() <= self.comms_timeout_s
