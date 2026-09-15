"""Generate a reference checkpoint.bin file with correctly packed NF4 data.

This script packs pre-determined test indices and absmax values into the
NF4Q binary checkpoint format. It uses only standard library (struct)
and does not contain any quantization logic.
"""
import struct

# Test data: 32 quantized indices spanning the full 4-bit range [0, 15]
indices = [
    15, 0, 12, 2, 7, 14, 0, 10, 11, 3, 9, 5, 13, 1, 8, 6,
    4, 15, 10, 7, 2, 12, 5, 9, 0, 14, 3, 11, 8, 1, 6, 13,
]
absmax_values = [2.5, 1.8]
blocksize = 16

with open('/app/checkpoint.bin', 'wb') as f:
    # Header
    f.write(b'NF4Q')
    f.write(struct.pack('<I', len(indices)))
    f.write(struct.pack('<I', blocksize))
    f.write(struct.pack('<I', len(absmax_values)))
    # Absmax values
    for am in absmax_values:
        f.write(struct.pack('<f', am))
    # Packed indices: low nibble = first index, high nibble = second index
    for i in range(0, len(indices), 2):
        low = indices[i] & 0xF
        high = (indices[i + 1] & 0xF) if i + 1 < len(indices) else 0
        f.write(struct.pack('B', low | (high << 4)))
