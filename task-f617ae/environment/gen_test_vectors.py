#!/usr/bin/env python3
"""Generate test vectors for the VM key validation algorithm.
Outputs test_vectors.json in the current directory."""

import json

M = 0xFFFFFFFF
MAGIC  = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2 = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]


def compute_groups(seed):
    groups = []
    s = seed
    for i in range(5):
        val = s
        val = ((val ^ MAGIC[i]) * PRIMES[i]) & M
        val = ((val >> 13) | (val << 19)) & M
        val = (val ^ (val >> 16)) & M
        val = ((val + ROUND2[i]) & M) ^ s
        val = val & M
        val = ((val << 7) | (val >> 25)) & M
        val = (val * 0x5BD1E995) & M
        val = (val ^ (val >> 15)) & M
        groups.append(val)
        s = ((s ^ val) + MAGIC[i]) & M
        s = ((s >> 11) | (s << 21)) & M
        s = (s * 0x1B873593) & M
    return groups


test_vectors = []

# 15 valid cases (result = 0 = accept)
valid_seeds = [
    0x5F3759DF, 0x12345678, 0xDEADBEEF, 0x00000000, 0xFFFFFFFF,
    0xCAFEBABE, 0x0BADF00D, 0x8BADF00D, 0x42424242, 0xA5A5A5A5,
    0x13371337, 0xFEEDFACE, 0xBEEFCAFE, 0x00C0FFEE, 0xDECAFBAD,
]
for seed in valid_seeds:
    groups = compute_groups(seed)
    test_vectors.append({
        "seed": f"{seed:08X}",
        "groups": [f"{g:08X}" for g in groups],
        "expected": 0,
    })

# 10 invalid cases — corrupt one group each, covering all 5 group indices
for idx, seed in enumerate(valid_seeds[:10]):
    groups = compute_groups(seed)
    corrupt_group = idx % 5  # ensures groups 0-4 each corrupted twice
    groups[corrupt_group] ^= 0x01
    test_vectors.append({
        "seed": f"{seed:08X}",
        "groups": [f"{g:08X}" for g in groups],
        "expected": 1,
    })

with open("test_vectors.json", "w") as f:
    json.dump(test_vectors, f, indent=2)

print(f"Generated {len(test_vectors)} test vectors")
