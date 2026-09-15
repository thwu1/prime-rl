#!/usr/bin/env python3
"""Generate 100 challenge IEEE 754 doubles as raw big-endian binary."""
import struct
import random

random.seed(20260601)

values = []

# Special values (5): indices 0-4
values.append(struct.pack('>d', 0.0))
values.append(struct.pack('>d', -0.0))
values.append(struct.pack('>d', float('inf')))
values.append(struct.pack('>d', float('-inf')))
values.append(struct.pack('>d', float('nan')))

# Exact simple values (10): indices 5-14
for v in [1.0, 2.0, -3.0, 10.0, -100.0, 0.5, 0.25, 16.0, 1024.0, 0.125]:
    values.append(struct.pack('>d', v))

# Powers of 10 where notation choice matters (10): indices 15-24
for v in [1e-4, 1e-5, 1e-6, 1e-10, 1e-20, 1e7, 1e10, 1e20, 1e3, 1e-3]:
    values.append(struct.pack('>d', v))

# Near notation crossover (5): indices 25-29
for v in [0.1, 0.01, 100.0, 1000.0, -1e15]:
    values.append(struct.pack('>d', v))

# Multi-digit values (15): indices 30-44
for v in [1.5e-4, -3.14, 2.718281828459045, 3.141592653589793,
          0.3, 0.7, 1.1, 9.9, 1.5, 6.7, 1.23, 9.87, 12.34,
          123.456, 1234.5678]:
    values.append(struct.pack('>d', v))

# Boundary values via direct hex (8): indices 45-52
for h in ["0000000000000001", "8000000000000001", "000FFFFFFFFFFFFF",
          "0010000000000000", "7FEFFFFFFFFFFFFF", "FFEFFFFFFFFFFFFF",
          "3FE0000000000001", "3FF0000000000001"]:
    values.append(bytes.fromhex(h))

# Near powers of 10 (5): indices 53-57
for v in [9.999999999999998, 10.000000000000002,
          0.09999999999999999, 99.99999999999999,
          999.9999999999999]:
    values.append(struct.pack('>d', v))

# Values needing many significant digits (7): indices 58-64
for v in [1.0000000000000002, 2.2250738585072014e-308,
          2.2250738585072009e-308, 1.7976931348623157e+308,
          4.9406564584124654e-324, 2.2204460492503131e-16,
          1.1125369292536007e-308]:
    values.append(struct.pack('>d', v))

# Random values spanning exponent range: indices 65-99
while len(values) < 100:
    exp = random.randint(1, 2046)
    mantissa = random.getrandbits(52)
    sign = random.randint(0, 1)
    bits = (sign << 63) | (exp << 52) | mantissa
    values.append(struct.pack('>Q', bits))

assert len(values) == 100

with open('/app/challenge.bin', 'wb') as f:
    for v in values:
        f.write(v)
