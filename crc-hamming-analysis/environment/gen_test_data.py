#!/usr/bin/env python3
"""Generate binary test data file for CRC-8 analysis task."""
import struct

vectors = [
    ("alpha", bytes([0x48])),
    ("bravo", bytes([0x54, 0x45, 0x53, 0x54])),
    ("charlie", bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08])),
]

with open("/app/test_data.bin", "wb") as f:
    f.write(b"CRC8")
    f.write(struct.pack("B", 1))
    f.write(struct.pack("B", len(vectors)))
    for name, data in vectors:
        name_bytes = name.encode("ascii")
        f.write(struct.pack("B", len(name_bytes)))
        f.write(name_bytes)
        f.write(struct.pack(">H", len(data)))
        f.write(data)
