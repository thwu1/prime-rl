from network.transport import Transport
from network.protocol import Packet


def test_fragment():
    t = Transport(mtu=10)
    p = Packet({"t": 1}, b"x" * 20)
    frags = t.fragment(p)
    assert len(frags) > 1


def test_reassemble():
    t = Transport(mtu=1500)
    p = Packet({"type": "test"}, b"payload")
    frags = t.fragment(p)
    result = t.reassemble(frags)
    assert result.payload == b"payload"
