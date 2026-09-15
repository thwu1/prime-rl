#!/usr/bin/env python3
import random
import struct

random.seed(42)
n, m = 3000, 400

with open('/app/input.bin', 'wb') as f:
    f.write(struct.pack('ii', n, m))
    for i in range(n):
        row = [random.gauss(0, 1) for _ in range(m)]
        f.write(struct.pack(f'{m}d', *row))

print(f"Generated input.bin: {n} rows x {m} cols")
