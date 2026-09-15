#!/usr/bin/env python3
"""Create binary test input files for DDL interpreter tests."""
import os
import struct

os.makedirs('/app/inputs', exist_ok=True)

# Input 1: container format
# DPK magic + version=2 + 2 chunks (HEAD with 3 bytes, DATA with 2 bytes)
data = bytearray()
data += bytes([0x44, 0x50, 0x4B])       # Magic "DPK"
data += bytes([0x02])                     # version = 2
data += struct.pack('>H', 2)              # num_chunks = 2
# Chunk 1: type=0x48454144 ("HEAD"), len=3, payload=[10,11,12]
data += struct.pack('>I', 0x48454144)
data += struct.pack('>I', 3)
data += bytes([0x0A, 0x0B, 0x0C])
# Chunk 2: type=0x44415441 ("DATA"), len=2, payload=[255,254]
data += struct.pack('>I', 0x44415441)
data += struct.pack('>I', 2)
data += bytes([0xFF, 0xFE])
with open('/app/inputs/input_container.bin', 'wb') as f:
    f.write(data)

# Input 2: tagged format
# "TG" magic + 3 records with different type tags
data = bytearray()
data += bytes([0x54, 0x47])               # Magic "TG"
data += bytes([0x01, 0xFF])               # Record: tag=1, byte_rec=255
data += bytes([0x02])                     # Record: tag=2
data += struct.pack('>H', 256)            # short_rec=256
data += bytes([0x03])                     # Record: tag=3
data += struct.pack('>I', 42)             # int_rec=42
with open('/app/inputs/input_tagged.bin', 'wb') as f:
    f.write(data)

# Input 3: choice format
# "CHO" magic + 3 items mixing pairs and singles
data = bytearray()
data += bytes([0x43, 0x48, 0x4F])         # Magic "CHO"
data += bytes([0x02, 0xAA, 0xBB])         # pair: first=170, second=187
data += bytes([0x01, 0xCC])               # single: value=204
data += bytes([0x02, 0x11, 0x22])         # pair: first=17, second=34
with open('/app/inputs/input_choice.bin', 'wb') as f:
    f.write(data)

# Input 4: chunk_stream format
# "CS" magic + 2 size-delimited frames
data = bytearray()
data += bytes([0x43, 0x53])               # Magic "CS"
data += struct.pack('>H', 4)              # Frame 1 size=4
data += bytes([0x01, 0xAA, 0xBB, 0xCC])   # type=1, data=[170,187,204]
data += struct.pack('>H', 3)              # Frame 2 size=3
data += bytes([0x02, 0xDD, 0xEE])         # type=2, data=[221,238]
with open('/app/inputs/input_chunk.bin', 'wb') as f:
    f.write(data)

# Input 5: truncated container (error case - should cause parse failure)
data = bytearray()
data += bytes([0x44, 0x50, 0x4B])         # Magic "DPK"
data += bytes([0x02])                     # version
data += struct.pack('>H', 2)              # num_chunks = 2
data += bytes([0x48, 0x45])               # only 2 bytes of chunk_type (need 4)
with open('/app/inputs/input_truncated.bin', 'wb') as f:
    f.write(data)

print("Created all test inputs.")
