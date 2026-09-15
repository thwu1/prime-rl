#!/usr/bin/env python3
"""Apply deterministic corruption to generated WAL data.
This script is deleted after execution during Docker build."""
import struct
import os
import sys

waldir = sys.argv[1]

# Corrupt snapshot: flip a byte in the state JSON data
snap_path = os.path.join(waldir, "snapshot_0000000040.snap")
with open(snap_path, 'rb') as f:
    data = bytearray(f.read())
# State data starts at offset 26 (magic:4 + version:2 + last_index:8 + last_term:8 + state_len:4)
data[30] ^= 0x20
with open(snap_path, 'wb') as f:
    f.write(data)

# Corrupt entry 53 in segment_0000000041.wal: flip a payload byte
seg_path = os.path.join(waldir, "segment_0000000041.wal")
with open(seg_path, 'rb') as f:
    data = bytearray(f.read())
offset = 18  # skip segment header
for i in range(12):  # skip entries 41-52 (12 entries)
    payload_len = struct.unpack_from('<I', data, offset + 24)[0]
    offset += 28 + payload_len + 4
# Now at entry 53; flip byte 5 of its payload
data[offset + 28 + 5] ^= 0xFF
with open(seg_path, 'wb') as f:
    f.write(data)

# Truncate segment_0000000081.wal: remove last 20 bytes to break entry 100
seg5_path = os.path.join(waldir, "segment_0000000081.wal")
size = os.path.getsize(seg5_path)
with open(seg5_path, 'r+b') as f:
    f.truncate(size - 20)
