#!/usr/bin/env python3
"""Generate NUMDATA1 binary archive for the parser task."""
import struct
import random
import base64
import math
import os

MAGIC = b"NUMDATA1"
SEED = 0x4E554D44


def generate():
    random.seed(SEED)
    records = []

    # --- Type 1: Raw IEEE 754 binary64, little-endian (250 total) ---
    for _ in range(230):
        val = random.uniform(-1000.0, 1000.0)
        records.append((1, struct.pack('<d', val)))

    type1_edges = [
        0.0, -0.0, 1.0, -1.0, 0.1, 0.2, 0.3,
        math.pi, math.e,
        float.fromhex('0x1.0000000000001p+0'),   # 1 + machine epsilon
        float.fromhex('0x1.0000000000002p+0'),   # 1 + 2*epsilon
        5e-324,                                   # smallest positive subnormal
        -5e-324,                                  # smallest negative subnormal
        1e-310,                                   # subnormal
        float.fromhex('0x1.0p-1022'),            # smallest positive normal
        float.fromhex('0x0.fffffffffffffp-1022'),# largest subnormal
        1234.5678,
        -9876.5432,
        0.333333333333333,
        42.0,
    ]
    for val in type1_edges:
        records.append((1, struct.pack('<d', val)))

    # --- Type 2: Decimal ASCII string (250 total) ---
    for _ in range(220):
        mi = random.randint(0, 9)
        fl = random.randint(1, 16)
        fd = ''.join(str(random.randint(0, 9)) for _ in range(fl))
        exp = random.randint(-15, 15)
        sign = random.choice(['', '-'])
        s = f"{sign}{mi}.{fd}e{exp}"
        enc = s.encode('ascii')
        records.append((2, struct.pack('<H', len(enc)) + enc))

    type2_adversarial = [
        "0.0", "-0.0", "1.0000000000000002",
        "9007199254740992.0", "9007199254740993.0",
        "0.1", "0.2", "0.3",
        "1e-400", "1e15", "1e-15",
        "2.2204460492503131e-16",
        "3.14159265358979323846264338327950288419716939937510",
        "2.71828182845904523536028747135266249775724709369995",
        "0.5", "0.25", "0.125", "0.0625",
        "1.5", "3.5", "7.5",
        "100.000000000000000000000",
        "0.00100000000000000000000",
        "1E10", "1e+10", "1e-10",
        "5e-324", "4.9406564584124654e-324",
        "2.2250738585072014e-308",
        "2.2250738585072013e-308",
    ]
    for s in type2_adversarial:
        enc = s.encode('ascii')
        records.append((2, struct.pack('<H', len(enc)) + enc))

    # --- Type 3: Base64-encoded IEEE 754 binary64 LE (200 total) ---
    for _ in range(190):
        val = random.uniform(-500.0, 500.0)
        raw = struct.pack('<d', val)
        b64 = base64.b64encode(raw)
        records.append((3, struct.pack('<H', len(b64)) + b64))

    type3_edges = [
        0.0, -0.0, 1.0, -1.0, math.pi, math.e,
        5e-324, 1e-310,
        float.fromhex('0x1.0p-1022'),
        float.fromhex('0x0.fffffffffffffp-1022'),
    ]
    for val in type3_edges:
        raw = struct.pack('<d', val)
        b64 = base64.b64encode(raw)
        records.append((3, struct.pack('<H', len(b64)) + b64))

    # --- Type 4: Hex float string (150 total) ---
    for _ in range(140):
        val = random.uniform(-100.0, 100.0)
        s = val.hex()
        enc = s.encode('ascii')
        records.append((4, struct.pack('<H', len(enc)) + enc))

    type4_edges = [
        "0x0.0p+0",
        "-0x0.0p+0",
        "0x1.921fb54442d18p+1",
        "0x1.5bf0a8b145769p+1",
        "0x1.0p+0",
        "-0x1.0p+0",
        "0x1.8p+0",
        "0x0.0000000000001p-1022",
        "0x1.0p-1022",
        "0x1.0p+10",
    ]
    for s in type4_edges:
        enc = s.encode('ascii')
        records.append((4, struct.pack('<H', len(enc)) + enc))

    # --- Type 5: Scaled integer, big-endian mantissa (150 total) ---
    for _ in range(140):
        integer = random.randint(-10**15, 10**15)
        scale = random.randint(0, 15)
        records.append((5, struct.pack('>q', integer) + struct.pack('B', scale)))

    type5_edges = [
        (0, 0), (1, 0), (-1, 0),
        (314159265358979, 14),
        (271828182845904, 14),
        (1000000000000000, 15),
        (-1000000000000000, 15),
        (1, 18),
        (999999999999999, 0),
        (123456789, 5),
    ]
    for integer, scale in type5_edges:
        records.append((5, struct.pack('>q', integer) + struct.pack('B', scale)))

    # Deterministic shuffle
    random.shuffle(records)

    # Write binary archive
    os.makedirs('/app', exist_ok=True)
    with open('/app/data.bin', 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<I', len(records)))
        for tid, payload in records:
            f.write(struct.pack('B', tid) + payload)


if __name__ == '__main__':
    generate()
