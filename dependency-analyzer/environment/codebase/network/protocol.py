"""Network protocol definitions."""

import json


class Packet:
    """A network packet with header and payload."""

    def __init__(self, header: dict, payload: bytes):
        self.header = header
        self.payload = payload

    def serialize(self) -> bytes:
        """Serialize the packet to bytes."""
        header_bytes = json.dumps(self.header).encode()
        return len(header_bytes).to_bytes(4, "big") + header_bytes + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> "Packet":
        """Deserialize bytes into a Packet."""
        header_len = int.from_bytes(data[:4], "big")
        header = json.loads(data[4 : 4 + header_len])
        payload = data[4 + header_len :]
        return cls(header, payload)
