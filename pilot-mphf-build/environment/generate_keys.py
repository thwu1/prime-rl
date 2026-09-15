#!/usr/bin/env python3
"""Generate deterministic key datasets for MPHF testing."""
import os, random

os.makedirs("/app/data", exist_ok=True)

# 1,000 random uint64 keys
rng = random.Random(12345)
keys = set()
while len(keys) < 1000:
    keys.add(rng.randint(0, (1 << 63) - 1))
with open("/app/data/random_1k.txt", "w") as f:
    for k in sorted(keys):
        f.write(f"{k}\n")

# 200,000 random uint64 keys
rng = random.Random(99999)
keys = set()
while len(keys) < 200000:
    keys.add(rng.randint(0, (1 << 63) - 1))
with open("/app/data/random_200k.txt", "w") as f:
    for k in sorted(keys):
        f.write(f"{k}\n")

# 1,000,000 random uint64 keys
rng = random.Random(77777)
keys = set()
while len(keys) < 1000000:
    keys.add(rng.randint(0, (1 << 63) - 1))
with open("/app/data/random_1m.txt", "w") as f:
    for k in sorted(keys):
        f.write(f"{k}\n")

# 10,000 sequential integer keys (0 .. 9999)
with open("/app/data/sequential_10k.txt", "w") as f:
    for k in range(10000):
        f.write(f"{k}\n")

# 20,000 adversarial keys: only high 32 bits vary (bottom 32 bits = 0).
# Exposes hash functions with poor mixing between high and low halves.
with open("/app/data/adversarial_20k.txt", "w") as f:
    for i in range(20000):
        f.write(f"{i << 32}\n")
