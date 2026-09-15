#!/usr/bin/env python3
"""Generate sample MLP packet files for /app/samples/."""
import struct
import os

LFSR_POLY = 0xB4BCD35C
LFSR_ZERO_SEED = 0x0000ACE1


def crc16_ccitt(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def build_packet(msg_type, payload):
    header = bytearray(8)
    header[0:2] = b'ML'
    header[2] = 1
    header[3] = msg_type
    struct.pack_into('>H', header, 4, len(payload))
    crc_data = bytes(header[2:6]) + payload
    crc = crc16_ccitt(crc_data)
    struct.pack_into('>H', header, 6, crc)
    return bytes(header) + payload


def lfsr_scramble(data, seq):
    """Scramble data using Galois LFSR keystream."""
    state = seq if seq != 0 else LFSR_ZERO_SEED
    result = bytearray(len(data))
    for i in range(len(data)):
        lsb = state & 1
        state >>= 1
        if lsb:
            state ^= LFSR_POLY
        state &= 0xFFFFFFFF
        result[i] = data[i] ^ (state & 0xFF)
    return bytes(result)


os.makedirs('/app/samples', exist_ok=True)

# mixed.bin: one of each valid message type
data = bytearray()
data.extend(build_packet(0, struct.pack('>I', 0x00000001) + b'gateway\x00'))
data.extend(build_packet(1, struct.pack('>B', 1) + struct.pack('>I', 100) + b'Hello, MeshLink!'))
data.extend(build_packet(2, struct.pack('>I', 100)))
data.extend(build_packet(3, struct.pack('>H', 0x0002) + b'connection reset'))
data.extend(build_packet(4, struct.pack('>B', 3) + struct.pack('>III', 1, 2, 3)))
data.extend(build_packet(5, struct.pack('>I', 0x1000) + struct.pack('>HH', 0, 2) + b'fragA'))
with open('/app/samples/mixed.bin', 'wb') as f:
    f.write(data)

# errors.bin: various error conditions
data = bytearray()
data.extend(build_packet(2, struct.pack('>I', 1)))
data.extend(b'XX\x01\x02\x00\x04\x00\x00\x00\x00\x00\x02')
data.extend(build_packet(2, struct.pack('>I', 3)))
data.extend(b'ML\x01\x01\x00\x20')
with open('/app/samples/errors.bin', 'wb') as f:
    f.write(data)

# fragments.bin: fragmented message (complete, 3 parts)
data = bytearray()
data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 0, 3) + b'Hello, '))
data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 1, 3) + b'MeshLink '))
data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 2, 3) + b'Protocol!'))
with open('/app/samples/fragments.bin', 'wb') as f:
    f.write(data)

# scrambled.bin: DATA packets on secure channels (>= 128)
data = bytearray()
seq1 = 0xAABBCCDD
original1 = b'Secure payload data'
scrambled1 = lfsr_scramble(original1, seq1)
data.extend(build_packet(1, struct.pack('>B', 0x80) + struct.pack('>I', seq1) + scrambled1))
seq2 = 0x11223344
original2 = b'Another secret'
scrambled2 = lfsr_scramble(original2, seq2)
data.extend(build_packet(1, struct.pack('>B', 0xFF) + struct.pack('>I', seq2) + scrambled2))
# Normal (unscrambled) DATA for comparison
data.extend(build_packet(1, struct.pack('>B', 5) + struct.pack('>I', 42) + b'plaintext'))
with open('/app/samples/scrambled.bin', 'wb') as f:
    f.write(data)

print("Sample files generated in /app/samples/")
