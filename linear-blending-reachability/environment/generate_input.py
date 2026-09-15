#!/usr/bin/env python3
"""Generate deterministic input data for the linear blending reachability task."""
import random
import os

random.seed(42)
n = 5000
k = 500
m = 10000

a = [random.randint(501, 9500) for _ in range(n)]

os.makedirs('/app', exist_ok=True)
with open('/app/input.txt', 'w') as f:
    f.write(f'{n} {m} {k}\n')
    f.write(' '.join(map(str, a)) + '\n')
