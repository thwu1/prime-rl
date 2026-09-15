#!/usr/bin/env python3
"""Recover original file data from the binary crash dump.

"""
import struct
import hashlib
import sys

sys.path.insert(0, '/opt/ec_libs')
from reed_solomon import decode

with open('/app/crash_dump.bin', 'rb') as f:
    magic = f.read(8)
    assert magic == b'ECDUMP01', f"bad magic: {magic}"
    k, m, original_size = struct.unpack('<III', f.read(12))
    checksum = f.read(32)
    num_shards, = struct.unpack('<I', f.read(4))

    shards = []
    indices = []
    for _ in range(num_shards):
        idx, length = struct.unpack('<II', f.read(8))
        shard_data = f.read(length)
        shards.append(shard_data)
        indices.append(idx)

recovered_shards = decode(shards, k, m, indices)
recovered = b''.join(recovered_shards)[:original_size]

assert hashlib.sha256(recovered).digest() == checksum, "checksum mismatch"

with open('/app/recovered.bin', 'wb') as f:
    f.write(recovered)

print(f"Recovered {len(recovered)} bytes, checksum verified.")
