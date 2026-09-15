#!/usr/bin/env python3
"""
Fix calculator.py by rewriting it with the correct Nix store path algorithm.

"""

CORRECT_CALCULATOR = r'''#!/usr/bin/env python3
"""
Nix Store Path Calculator for Fixed-Output Derivations

Computes /nix/store paths from content hashes using the Nix store path
algorithm. Reads derivation specifications from /app/queries.json and
writes computed store paths to /app/results.json.

See /app/reference.md for the algorithm specification.
"""

import hashlib
import json
import sys

# Nix custom base-32 alphabet: digits 0-9 plus lowercase with e,o,t,u omitted
NIX32_CHARS = '0123456789abcdfghijklmnpqrsvwxyz'


def to_nix32(data: bytes) -> str:
    """Encode raw bytes as a Nix base-32 string.

    Processes 5-bit groups from most significant to least significant,
    mapping each group through NIX32_CHARS.
    """
    bit_count = len(data) * 8
    hash_len = (bit_count + 4) // 5

    result = []
    for n in range(hash_len - 1, -1, -1):
        b = 0
        for bit in range(5):
            src_bit = n * 5 + bit
            if src_bit < bit_count:
                byte_idx = src_bit // 8
                bit_idx = src_bit % 8   # LSB-first within each byte
                if data[byte_idx] & (1 << bit_idx):
                    b |= 1 << bit
        result.append(NIX32_CHARS[b])

    return ''.join(result)


def compress_hash(digest: bytes, target_size: int) -> bytes:
    """Compress a hash digest to target_size bytes via XOR folding."""
    result = bytearray(target_size)
    for i, b in enumerate(digest):
        result[i % target_size] ^= b
    return bytes(result)


def compute_store_path(hash_hex: str, name: str, recursive: bool) -> str:
    """Compute the /nix/store path for a fixed-output derivation."""
    if recursive:
        # Recursive FODs use source: prefix with the content hash directly
        fingerprint = f'source:sha256:{hash_hex}:/nix/store:{name}'
    else:
        # Flat FODs: compute inner hash first, then use output: prefix
        inner = hashlib.sha256(
            f'fixed:out:sha256:{hash_hex}:'.encode()
        ).hexdigest()
        fingerprint = f'output:out:sha256:{inner}:/nix/store:{name}'

    digest = hashlib.sha256(fingerprint.encode()).digest()
    compressed = compress_hash(digest, 20)
    store_hash = to_nix32(compressed)

    return f'/nix/store/{store_hash}-{name}'


def main():
    with open('/app/queries.json', 'r') as f:
        queries = json.load(f)

    results = {}
    for q in queries:
        path = compute_store_path(q['hash_hex'], q['name'], q['recursive'])
        results[q['name']] = path

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f'Computed {len(results)} store paths -> /app/results.json')


if __name__ == '__main__':
    main()
'''

with open('/app/calculator.py', 'w') as f:
    f.write(CORRECT_CALCULATOR)

print("calculator.py fixed with correct implementation")
