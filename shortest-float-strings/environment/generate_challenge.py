#!/usr/bin/env python3
"""Generate 100 challenge IEEE 754 doubles for shortest-string conversion."""
import struct
import random

def d2h(d):
    """Double to 16-char big-endian hex of its IEEE 754 bit pattern."""
    return format(struct.unpack('>Q', struct.pack('>d', d))[0], '016X')

random.seed(20260601)

values = []

# === Special values (5) ===
values.append(d2h(0.0))
values.append(d2h(-0.0))
values.append(d2h(float('inf')))
values.append(d2h(float('-inf')))
values.append(d2h(float('nan')))

# === Exact simple values (10) ===
for v in [1.0, 2.0, -3.0, 10.0, -100.0, 0.5, 0.25, 16.0, 1024.0, 0.125]:
    values.append(d2h(v))

# === Powers of 10 where notation choice matters (10) ===
for v in [1e-4, 1e-5, 1e-6, 1e-10, 1e-20, 1e7, 1e10, 1e20, 1e3, 1e-3]:
    values.append(d2h(v))

# === Near notation crossover (5) ===
for v in [0.1, 0.01, 100.0, 1000.0, -1e15]:
    values.append(d2h(v))

# === Multi-digit values testing notation and precision (15) ===
for v in [1.5e-4, -3.14, 2.718281828459045, 3.141592653589793,
          0.3, 0.7, 1.1, 9.9, 1.5, 6.7, 1.23, 9.87, 12.34,
          123.456, 1234.5678]:
    values.append(d2h(v))

# === Boundary values via direct hex (8) ===
values.extend([
    "0000000000000001",  # smallest positive denormal ~5e-324
    "8000000000000001",  # smallest magnitude negative denormal
    "000FFFFFFFFFFFFF",  # largest denormal
    "0010000000000000",  # smallest positive normal ~2.2250738585072014e-308
    "7FEFFFFFFFFFFFFF",  # largest finite double ~1.7976931348623157e+308
    "FFEFFFFFFFFFFFFF",  # most negative finite double
    "3FE0000000000001",  # 0.5 + 1 ULP
    "3FF0000000000001",  # 1.0 + 1 ULP
])

# === Near powers of 10 (5) ===
for v in [9.999999999999998, 10.000000000000002,
          0.09999999999999999, 99.99999999999999,
          999.9999999999999]:
    values.append(d2h(v))

# === Values needing many significant digits (7) ===
for v in [1.0000000000000002, 2.2250738585072014e-308,
          2.2250738585072009e-308, 1.7976931348623157e+308,
          4.9406564584124654e-324, 2.2204460492503131e-16,
          1.1125369292536007e-308]:
    values.append(d2h(v))

# === Random values spanning exponent range (35) ===
for _ in range(100 - len(values)):
    exp = random.randint(1, 2046)
    mantissa = random.getrandbits(52)
    sign = random.randint(0, 1)
    bits = (sign << 63) | (exp << 52) | mantissa
    values.append(format(bits, '016X'))

assert len(values) == 100, f"Expected 100 values, got {len(values)}"

for v in values:
    print(v)
