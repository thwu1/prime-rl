"""
Packet module for UDP-based reliable transport protocol.

Header layout (18 bytes):
  checksum   : uint16 - Internet checksum (RFC 1071) over entire packet
  length     : uint16 - Total packet length in bytes
  ptype      : uint8  - Packet type (DATA=1, ACK=2, FIN=3, FIN_ACK=4)
  flags      : uint8  - Reserved
  seq_num    : uint32 - Byte-level sequence number
  ack_num    : uint32 - Cumulative acknowledgment (next expected byte)
  window     : uint16 - Receiver window advertisement (packets)
  sack_count : uint8  - Number of SACK blocks (0-3)
  reserved   : uint8  - Must be 0

Variable portion:
  SACK blocks : sack_count * 8 bytes, each (left_edge: uint32, right_edge: uint32)
  payload     : 0..500 bytes
"""

import struct

MAX_PAYLOAD = 500
HEADER_FORMAT = '!HHBBIIHBB'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 18
SACK_BLOCK_FORMAT = '!II'
SACK_BLOCK_SIZE = struct.calcsize(SACK_BLOCK_FORMAT)  # 8
MAX_SACK_BLOCKS = 3

TYPE_DATA = 1
TYPE_ACK = 2
TYPE_FIN = 3
TYPE_FIN_ACK = 4


def compute_checksum(data):
    """Internet checksum per RFC 1071."""
    if len(data) % 2:
        data = data + b'\x00'
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


class Packet:
    __slots__ = ('ptype', 'seq_num', 'ack_num', 'payload',
                 'window', 'sack_blocks', 'flags')

    def __init__(self, ptype, seq_num=0, ack_num=0, payload=b'',
                 window=0, sack_blocks=None, flags=0):
        self.ptype = ptype
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.payload = payload
        self.window = window
        self.sack_blocks = sack_blocks or []
        self.flags = flags

    def serialize(self):
        sack_count = min(len(self.sack_blocks), MAX_SACK_BLOCKS)
        total_len = HEADER_SIZE + sack_count * SACK_BLOCK_SIZE + len(self.payload)

        header = struct.pack(
            HEADER_FORMAT,
            0,                # checksum placeholder
            total_len,
            self.ptype,
            self.flags,
            self.seq_num & 0xFFFFFFFF,
            self.ack_num & 0xFFFFFFFF,
            self.window & 0xFFFF,
            sack_count,
            0,                # reserved
        )

        sack_data = b''
        for i in range(sack_count):
            left, right = self.sack_blocks[i]
            sack_data += struct.pack(SACK_BLOCK_FORMAT,
                                     left & 0xFFFFFFFF,
                                     right & 0xFFFFFFFF)

        raw = header + sack_data + self.payload
        checksum = compute_checksum(raw)
        raw = struct.pack('!H', checksum) + raw[2:]
        return raw

    @staticmethod
    def deserialize(data):
        if len(data) < HEADER_SIZE:
            return None

        # Valid packet checksum == 0
        if compute_checksum(data) != 0:
            return None

        hdr = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        (checksum, length, ptype, flags,
         seq_num, ack_num, window, sack_count, _reserved) = hdr

        if length != len(data):
            return None

        sack_blocks = []
        offset = HEADER_SIZE
        for _ in range(min(sack_count, MAX_SACK_BLOCKS)):
            if offset + SACK_BLOCK_SIZE > len(data):
                return None
            left, right = struct.unpack(SACK_BLOCK_FORMAT,
                                        data[offset:offset + SACK_BLOCK_SIZE])
            sack_blocks.append((left, right))
            offset += SACK_BLOCK_SIZE

        payload = data[offset:]
        return Packet(ptype, seq_num, ack_num, payload, window, sack_blocks, flags)
