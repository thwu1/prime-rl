#!/usr/bin/env python3
"""Generate deterministic test input: 1000 integers with seed 42."""
import random
random.seed(42)
for _ in range(1000):
    print(random.randint(1, 100000))
