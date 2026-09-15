"""
Packet format for the reliable transport protocol.

Fixed header (10 bytes):
  seq_num  : uint16 (big-endian) - packet sequence number
  ack_num  : uint16 (big-endian) - cumulative acknowledgment number (next expected seq)
  flags    : uint8               - control flags (DATA=0x01, ACK=0x02, FIN=0x04)
  window   : uint16 (big-endian) - advertised window size (in packets)
  n_sack   : uint8               - number of SACK blocks (0-4)
  checksum : uint16 (big-endian) - Internet checksum (RFC 1071)

SACK blocks (n_sack * 4 bytes each):
  left_edge  : uint16 - start of contiguously received range
  right_edge : uint16 - end (exclusive) of contiguously received range
  Represents the range [left_edge, right_edge) of received sequence numbers.

Payload (variable length):
  Up to MSS bytes of application data.

Sequence numbers are packet-level (each packet increments by 1) and wrap
around modulo 2^seq_bits, where seq_bits is configurable (8-16).
"""

import struct
from typing import Optional, List, Tuple


FLAG_DATA = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04

HEADER_BASE_FMT = '!HHBHB'
HEADER_BASE_SIZE = struct.calcsize(HEADER_BASE_FMT)  # 8 bytes
CHECKSUM_SIZE = 2
FULL_HEADER_SIZE = HEADER_BASE_SIZE + CHECKSUM_SIZE  # 10 bytes
SACK_BLOCK_FMT = '!HH'
SACK_BLOCK_SIZE = struct.calcsize(SACK_BLOCK_FMT)  # 4 bytes
MAX_SACK_BLOCKS = 4


def internet_checksum(data: bytes) -> int:
    """Compute the Internet checksum (RFC 1071) over the given data."""
    if len(data) % 2:
        data = data + b'\x00'
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


class Packet:
    """Network packet with header, optional SACK blocks, and payload."""

    __slots__ = ('seq_num', 'ack_num', 'flags', 'window', 'sack_blocks', 'payload')

    def __init__(self, seq_num: int = 0, ack_num: int = 0, flags: int = 0,
                 window: int = 0, sack_blocks: Optional[List[Tuple[int, int]]] = None,
                 payload: bytes = b''):
        self.seq_num = seq_num & 0xFFFF
        self.ack_num = ack_num & 0xFFFF
        self.flags = flags & 0xFF
        self.window = window & 0xFFFF
        self.sack_blocks = (sack_blocks or [])[:MAX_SACK_BLOCKS]
        self.payload = payload

    def serialize(self) -> bytes:
        """Serialize the packet to bytes with computed checksum."""
        n_sack = len(self.sack_blocks)
        hdr = struct.pack(HEADER_BASE_FMT, self.seq_num, self.ack_num,
                          self.flags, self.window, n_sack)
        sack_data = b''
        for left, right in self.sack_blocks:
            sack_data += struct.pack(SACK_BLOCK_FMT, left & 0xFFFF, right & 0xFFFF)
        # Checksum computed with the checksum field set to zero
        raw = hdr + b'\x00\x00' + sack_data + self.payload
        cksum = internet_checksum(raw)
        return hdr + struct.pack('!H', cksum) + sack_data + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> Optional['Packet']:
        """
        Deserialize bytes into a Packet. Returns None if the data is too
        short, has an invalid SACK count, or fails the checksum.
        """
        if len(data) < FULL_HEADER_SIZE:
            return None
        seq_num, ack_num, flags, window, n_sack = struct.unpack(
            HEADER_BASE_FMT, data[:HEADER_BASE_SIZE])
        checksum = struct.unpack('!H', data[HEADER_BASE_SIZE:FULL_HEADER_SIZE])[0]
        if n_sack > MAX_SACK_BLOCKS:
            return None
        sack_end = FULL_HEADER_SIZE + n_sack * SACK_BLOCK_SIZE
        if len(data) < sack_end:
            return None
        # Verify checksum: recompute with checksum field zeroed
        verify = data[:HEADER_BASE_SIZE] + b'\x00\x00' + data[FULL_HEADER_SIZE:]
        if internet_checksum(verify) != checksum:
            return None
        sack_blocks = []
        for i in range(n_sack):
            off = FULL_HEADER_SIZE + i * SACK_BLOCK_SIZE
            left, right = struct.unpack(SACK_BLOCK_FMT, data[off:off + SACK_BLOCK_SIZE])
            sack_blocks.append((left, right))
        payload = data[sack_end:]
        return cls(seq_num, ack_num, flags, window, sack_blocks, payload)
