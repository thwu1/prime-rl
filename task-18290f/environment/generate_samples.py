#!/usr/bin/env python3
"""
Generate deterministic binary test samples for NIST SP800-22 analysis.
Each sample is 125,000 bytes (1,000,000 bits).

"""

import random
import hashlib
import os

SAMPLE_DIR = "/app/samples"
N_BYTES = 125000  # 1,000,000 bits


def generate_sha256_stream(seed=42):
    """SHA-256 counter mode - cryptographically strong, passes all tests."""
    data = bytearray()
    counter = 0
    seed_bytes = seed.to_bytes(8, "big")
    while len(data) < N_BYTES:
        h = hashlib.sha256(seed_bytes + counter.to_bytes(8, "big")).digest()
        data.extend(h)
        counter += 1
    return bytes(data[:N_BYTES])


def generate_lcg_small_modulus(seed=54321):
    """LCG with modulus 2^16. Period = 65536. Extracts high byte."""
    a = 25173
    c = 13849
    m = 65536
    state = seed % m
    result = bytearray(N_BYTES)
    for i in range(N_BYTES):
        state = (a * state + c) % m
        result[i] = (state >> 8) & 0xFF
    return bytes(result)


def generate_biased_coin(seed=98765):
    """Biased coin: P(1) = 0.45 per bit."""
    rng = random.Random(seed)
    result = bytearray(N_BYTES)
    for i in range(N_BYTES):
        byte_val = 0
        for bit in range(8):
            byte_val = (byte_val << 1) | (1 if rng.random() < 0.45 else 0)
        result[i] = byte_val
    return bytes(result)


def generate_lfsr16(seed=0xACE1):
    """16-bit LFSR: x^16 + x^14 + x^13 + x^11 + 1 (maximal length)."""
    state = seed & 0xFFFF
    if state == 0:
        state = 1
    result = bytearray(N_BYTES)
    for i in range(N_BYTES):
        byte_val = 0
        for bit in range(8):
            feedback = (
                (state >> 15) ^ (state >> 13) ^ (state >> 12) ^ (state >> 10)
            ) & 1
            state = ((state << 1) | feedback) & 0xFFFF
            byte_val = (byte_val << 1) | (state & 1)
        result[i] = byte_val
    return bytes(result)


def generate_markov_chain(seed=11111):
    """Binary Markov chain: P(0->1) = P(1->0) = 0.3 (symmetric, balanced)."""
    rng = random.Random(seed)
    curr = 0
    result = bytearray(N_BYTES)
    for i in range(N_BYTES):
        byte_val = 0
        for bit in range(8):
            if rng.random() < 0.3:
                curr = 1 - curr
            byte_val = (byte_val << 1) | curr
        result[i] = byte_val
    return bytes(result)


def main():
    os.makedirs(SAMPLE_DIR, exist_ok=True)

    generators = [
        ("sample_alpha.bin", generate_sha256_stream),
        ("sample_beta.bin", generate_lcg_small_modulus),
        ("sample_gamma.bin", generate_biased_coin),
        ("sample_delta.bin", generate_lfsr16),
        ("sample_epsilon.bin", generate_markov_chain),
    ]

    for filename, gen_func in generators:
        filepath = os.path.join(SAMPLE_DIR, filename)
        data = gen_func()
        with open(filepath, "wb") as f:
            f.write(data)
        ones = sum(bin(b).count("1") for b in data)
        total = len(data) * 8
        print(
            f"Generated {filepath}: {len(data)} bytes, "
            f"{ones}/{total} ones ({ones / total:.4f})"
        )


if __name__ == "__main__":
    main()
