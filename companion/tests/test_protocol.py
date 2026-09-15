from companion.comms.protocol import Envelope, MessageType, SequenceCounter, make_envelope


def test_envelope_json_round_trip():
    envelope = make_envelope(MessageType.TARGET_SELECT, {"x": 1, "y": 2, "w": 3, "h": 4}, seq=1)
    raw = envelope.to_json()
    parsed = Envelope.from_json(raw)
    assert parsed.type == MessageType.TARGET_SELECT
    assert parsed.seq == 1
    assert parsed.payload == {"x": 1, "y": 2, "w": 3, "h": 4}


def test_sequence_counter_increments():
    counter = SequenceCounter()
    assert counter.next() == 1
    assert counter.next() == 2
    assert counter.next() == 3
