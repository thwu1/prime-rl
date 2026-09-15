"""Transport layer implementation."""

from network.protocol import Packet


class Transport:
    """Handles packet fragmentation and reassembly."""

    def __init__(self, mtu: int = 1500):
        self.mtu = mtu

    def fragment(self, packet: Packet) -> list:
        """Fragment a packet if it exceeds MTU."""
        data = packet.serialize()
        if len(data) <= self.mtu:
            return [data]
        return [data[i : i + self.mtu] for i in range(0, len(data), self.mtu)]

    def reassemble(self, fragments: list) -> Packet:
        """Reassemble fragments into a packet."""
        return Packet.deserialize(b"".join(fragments))
