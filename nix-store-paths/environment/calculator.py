#!/usr/bin/env python3
"""
Nix Store Path Calculator

Computes Nix store paths for fixed-output derivations.

Usage:
    python3 calculator.py <sha256_hex> <name> [--recursive]
    python3 calculator.py --convert <sha256_hex>
"""

import hashlib
import sys
import base64


# Nix base-32 character set
NIX32_CHARS = '0123456789abcdefghijklmnopqrstuv'


def to_nix32(data: bytes) -> str:
    """Encode raw bytes as a Nix base-32 string."""
    bit_count = len(data) * 8
    hash_len = (bit_count + 4) // 5
    result = []
    for n in range(hash_len - 1, -1, -1):
        b = 0
        for bit in range(5):
            src_bit = n * 5 + bit
            if src_bit < bit_count:
                byte_idx = src_bit // 8
                bit_idx = 7 - (src_bit % 8)
                if data[byte_idx] & (1 << bit_idx):
                    b |= 1 << bit
        result.append(NIX32_CHARS[b])
    return ''.join(result)


def compress_hash(digest: bytes, target_size: int = 20) -> bytes:
    """Compress hash to target_size bytes by folding."""
    result = bytearray(target_size)
    for i, b in enumerate(digest):
        result[i % target_size] = (result[i % target_size] + b) % 256
    return bytes(result)


def compute_store_path(hash_hex: str, name: str, recursive: bool = False) -> str:
    """Compute /nix/store path for a fixed-output derivation."""
    if recursive:
        fingerprint = f'source:sha256:{hash_hex}:/nix/store:{name}'
    else:
        fingerprint = f'fixed:out:sha256:{hash_hex}:/nix/store:{name}'

    digest = hashlib.sha256(fingerprint.encode()).digest()
    compressed = compress_hash(digest)
    store_hash = to_nix32(compressed)
    return f'/nix/store/{store_hash}-{name}'


def convert_hash(hash_hex: str):
    """Convert hex hash to nix32 and SRI formats."""
    raw = bytes.fromhex(hash_hex)
    nix32 = to_nix32(raw)
    sri = f'sha256-{base64.b64encode(raw).decode()}'
    print(f'hex:   {hash_hex}')
    print(f'nix32: {nix32}')
    print(f'sri:   {sri}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == '--convert':
        if len(sys.argv) < 3:
            print("Usage: python3 calculator.py --convert <sha256_hex>")
            sys.exit(1)
        convert_hash(sys.argv[2])
    else:
        hash_hex = sys.argv[1]
        name = sys.argv[2] if len(sys.argv) > 2 else ''
        recursive = '--recursive' in sys.argv
        path = compute_store_path(hash_hex, name, recursive)
        print(path)
