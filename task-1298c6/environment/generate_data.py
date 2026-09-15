#!/usr/bin/env python3
"""Generate a deterministic set of IEEE 754 doubles for the shortest-string task."""
import struct
import math
import random
import os

random.seed(0x1337CAFE)

doubles = []
seen_bits = set()

def add(d):
    bits = struct.unpack('Q', struct.pack('d', d))[0]
    if bits not in seen_bits:
        seen_bits.add(bits)
        doubles.append(d)

# === Special values ===
add(0.0)
add(struct.unpack('d', struct.pack('Q', 1 << 63))[0])  # -0.0
add(float('inf'))
add(float('-inf'))
add(float('nan'))

# === Powers of 2 across full exponent range ===
for e in range(-1074, 1024, 37):
    add(math.ldexp(1.0, e))
    add(-math.ldexp(1.0, e))

# === Subnormal values ===
for i in [1, 2, 3, 7, 15, 100, 1000, 2**20, 2**35, 2**51, 2**52 - 1]:
    d = struct.unpack('d', struct.pack('Q', i))[0]
    add(d)
    add(-d)

# === Powers of 10 and their immediate IEEE 754 neighbors ===
for e in range(-22, 23):
    base = 10.0 ** e
    add(base)
    add(-base)
    bits = struct.unpack('Q', struct.pack('d', base))[0]
    if bits > 1:
        add(struct.unpack('d', struct.pack('Q', bits + 1))[0])
        add(struct.unpack('d', struct.pack('Q', bits - 1))[0])

# === Values where fixed vs scientific notation choice matters ===
for v in [0.00011, 0.0001, 0.00099, 0.001, 0.0099, 0.01, 0.099, 0.1,
          0.99, 1.0, 1.5, 9.9, 10.0, 99.0, 100.0, 999.0, 1000.0,
          9999.0, 10000.0, 99999.0, 100000.0,
          1e6, 1e7, 1e8, 1e10, 1e15, 1e20,
          1e-5, 1e-10, 1e-15, 1e-20,
          3.5e4, 7.77e-3, 1.23e12, 4.56e-9]:
    add(v)
    add(-v)

# === Mathematical constants and classic edge cases ===
for v in [0.5, 0.25, 0.125, 0.0625, 0.03125,
          1.0 / 3.0, 1.0 / 7.0, 1.0 / 11.0, 1.0 / 13.0, 1.0 / 17.0,
          math.pi, math.e, math.sqrt(2), math.log(2), math.log(10),
          2.2250738585072014e-308,     # smallest positive normal
          2.2250738585072009e-308,     # largest subnormal
          1.7976931348623157e+308,     # largest finite double
          1.7976931348623155e+308,     # second-largest finite
          5e-324,                      # smallest positive subnormal
          0.1 + 0.2,                   # 0.30000000000000004
          1.0 + 2**-52,               # 1 + machine epsilon
          1.0 - 2**-53,               # just below 1
          2.0 - 2**-52,               # just below 2
          (1 << 53) * 1.0,            # 2^53 (max exact integer)
          ((1 << 53) - 1) * 1.0,      # 2^53 - 1
          1e15 + 0.5,                  # near integer boundary
          0.000000000000001,           # 1e-15 alias
          123456789.0,
          123456789.123456789,
          9.999999999999998,           # just below 10
          99.99999999999999,           # just below 100
          ]:
    add(v)
    add(-v)

# === Fill to 1000 with random doubles across the full exponent range ===
while len(doubles) < 1000:
    exp = random.randint(1, 2046)  # Normal doubles (avoid subnormal=0 and special=2047)
    mantissa = random.randint(0, 2**52 - 1)
    sign = random.randint(0, 1)
    bits = (sign << 63) | (exp << 52) | mantissa
    d = struct.unpack('d', struct.pack('Q', bits))[0]
    add(d)

doubles = doubles[:1000]

os.makedirs('/app/data', exist_ok=True)
with open('/app/data/doubles.bin', 'wb') as f:
    f.write(struct.pack('<I', len(doubles)))
    for d in doubles:
        f.write(struct.pack('<d', d))

print(f"Generated {len(doubles)} test doubles to /app/data/doubles.bin")
