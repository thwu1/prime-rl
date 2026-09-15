#!/usr/bin/env python3
"""Generate crash_dump.bin at build time.

This script runs during the Docker build. It is deleted afterward —
only the binary output remains in the image.
"""
import struct
import hashlib
import sys
sys.path.insert(0, '/opt/ec_libs')
from reed_solomon import encode

# Deterministic data
data = bytes([(i * 37 + 13) % 256 for i in range(4500)])
k, m = 4, 2
shards = encode(data, k, m)
checksum = hashlib.sha256(data).digest()

# Simulate crash: shards at indices 2 (data) and 5 (parity) lost
available_indices = [0, 1, 3, 4]

with open('/app/crash_dump.bin', 'wb') as f:
    # Header
    f.write(b'ECDUMP01')                             # 8-byte magic
    f.write(struct.pack('<III', k, m, len(data)))     # 12 bytes
    f.write(checksum)                                 # 32 bytes
    f.write(struct.pack('<I', len(available_indices))) # 4 bytes
    # Shard records
    for idx in available_indices:
        shard = shards[idx]
        f.write(struct.pack('<II', idx, len(shard)))
        f.write(shard)

print(f"Generated crash_dump.bin: RS({k},{m}), "
      f"{len(data)} bytes, {len(available_indices)} surviving shards")
