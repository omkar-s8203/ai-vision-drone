import json

import pytest

from companion.comms.protocol import MessageType, make_envelope
from companion.comms.ws_server import GroundStationLink
from companion.tests.conftest import FakeTransport


@pytest.mark.asyncio
async def test_target_selected_dispatch():
    transport = FakeTransport()
    link = GroundStationLink(transport)
    received = {}
    link.on_target_selected(lambda payload: received.update(payload))

    envelope = make_envelope(MessageType.TARGET_SELECT, {"x": 1, "y": 2, "w": 3, "h": 4}, seq=1)
    transport.inject(envelope.to_json())

    assert received == {"x": 1, "y": 2, "w": 3, "h": 4}


@pytest.mark.asyncio
async def test_abort_dispatch():
    transport = FakeTransport()
    link = GroundStationLink(transport)
    calls = []
    link.on_abort(lambda payload: calls.append(payload))

    envelope = make_envelope(MessageType.ABORT, {"reason": "operator"}, seq=1)
    transport.inject(envelope.to_json())

    assert calls == [{"reason": "operator"}]


@pytest.mark.asyncio
async def test_webrtc_offer_dispatch():
    transport = FakeTransport()
    link = GroundStationLink(transport)
    calls = []
    link.on_webrtc_offer(lambda payload: calls.append(payload))

    envelope = make_envelope(MessageType.WEBRTC_OFFER, {"sdp": "v=0...", "sdp_type": "offer"}, seq=1)
    transport.inject(envelope.to_json())

    assert calls == [{"sdp": "v=0...", "sdp_type": "offer"}]


@pytest.mark.asyncio
async def test_send_webrtc_answer_broadcasts_envelope():
    transport = FakeTransport()
    link = GroundStationLink(transport)

    await link.send_webrtc_answer("v=0...", "answer")

    assert len(transport.sent) == 1
    parsed = json.loads(transport.sent[0])
    assert parsed["type"] == MessageType.WEBRTC_ANSWER
    assert parsed["payload"] == {"sdp": "v=0...", "sdp_type": "answer"}


@pytest.mark.asyncio
async def test_send_tracking_update_broadcasts_envelope():
    transport = FakeTransport()
    link = GroundStationLink(transport)

    await link.send_tracking_update({"state": "TRACKING"})

    assert len(transport.sent) == 1
    parsed = json.loads(transport.sent[0])
    assert parsed["type"] == MessageType.TRACKING_UPDATE
    assert parsed["payload"] == {"state": "TRACKING"}


@pytest.mark.asyncio
async def test_is_connected_reflects_transport():
    connected_link = GroundStationLink(FakeTransport(connected=True))
    disconnected_link = GroundStationLink(FakeTransport(connected=False))
    assert connected_link.is_connected is True
    assert disconnected_link.is_connected is False
