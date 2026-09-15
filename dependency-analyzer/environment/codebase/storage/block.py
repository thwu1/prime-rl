"""Block-level storage operations."""


class Block:
    """A fixed-size storage block."""

    BLOCK_SIZE = 4096

    def __init__(self, block_id: int, data: bytes = b""):
        self.block_id = block_id
        self.data = (data + bytes(self.BLOCK_SIZE))[: self.BLOCK_SIZE]

    def read(self, offset: int, length: int) -> bytes:
        """Read bytes from the block."""
        return self.data[offset : offset + length]

    def write(self, offset: int, data: bytes) -> None:
        """Write bytes into the block."""
        d = bytearray(self.data)
        d[offset : offset + len(data)] = data
        self.data = bytes(d)
