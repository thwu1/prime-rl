"""Generate reference.nf4 checkpoint and weights.bin benchmark data.

This script creates the binary test fixtures used by the task.
It is deleted after execution during Docker build.
"""
import struct
import random
import zlib

# Pre-determined quantized indices and scaling factors for the reference checkpoint
INDICES = [
    15, 0, 12, 2, 7, 14, 0, 10, 11, 3, 9, 5, 13, 1, 8, 6,
    4, 15, 10, 7, 2, 12, 5, 9, 0, 14, 3, 11, 8, 1, 6, 13,
]
ABSMAX = [2.5, 1.8]
BLOCKSIZE = 16

# Build NF4Q v2 binary content
body = bytearray()
body.extend(b'NF4Q')
body.extend(struct.pack('<H', 2))       # version
body.extend(struct.pack('<H', 0))       # reserved
body.extend(struct.pack('<I', len(INDICES)))
body.extend(struct.pack('<I', BLOCKSIZE))
body.extend(struct.pack('<I', len(ABSMAX)))

for am in ABSMAX:
    body.extend(struct.pack('<f', am))

# Pack nibbles: low nibble = first index, high nibble = second
for i in range(0, len(INDICES), 2):
    lo = INDICES[i] & 0xF
    hi = (INDICES[i + 1] & 0xF) if i + 1 < len(INDICES) else 0
    body.append(lo | (hi << 4))

# Append CRC32 footer
crc = zlib.crc32(bytes(body)) & 0xFFFFFFFF
body.extend(struct.pack('<I', crc))

with open('/app/reference.nf4', 'wb') as f:
    f.write(body)

# Generate benchmark weights: 1024 float32 values from N(0, 1)
random.seed(12345)
with open('/app/weights.bin', 'wb') as f:
    for _ in range(1024):
        f.write(struct.pack('<f', random.gauss(0, 1)))
