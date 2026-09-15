#!/usr/bin/env python3
"""Generate deterministic bitstream data for NIST SP 800-22 testing task."""
import hashlib
import json
import os
import random
import struct


def sha256_ctr_bits(seed_int, num_bits):
    """Generate high-quality pseudorandom bits using SHA-256 in counter mode."""
    seed_bytes = struct.pack('>I', seed_int)
    bits = []
    counter = 0
    while len(bits) < num_bits:
        data = seed_bytes + struct.pack('>Q', counter)
        h = hashlib.sha256(data).digest()
        for byte_val in h:
            for bit_pos in range(7, -1, -1):
                bits.append((byte_val >> bit_pos) & 1)
                if len(bits) >= num_bits:
                    return bits
        counter += 1
    return bits[:num_bits]


def periodic_bits(seed, base_length, total_bits):
    """Generate periodic bit sequence: random base repeated to fill length."""
    rng = random.Random(seed)
    base = [rng.randint(0, 1) for _ in range(base_length)]
    repeats = (total_bits + base_length - 1) // base_length
    full = (base * repeats)[:total_bits]
    return full


def biased_bits(seed, num_bits, p=0.47):
    """Generate biased Bernoulli bits with P(bit=1) = p."""
    rng = random.Random(seed)
    return [1 if rng.random() < p else 0 for _ in range(num_bits)]


def bits_to_bytes(bits):
    """Pack bits into bytes, MSB first."""
    result = bytearray()
    for i in range(0, len(bits), 8):
        byte_val = 0
        for j in range(8):
            byte_val <<= 1
            if i + j < len(bits):
                byte_val |= bits[i + j]
        result.append(byte_val)
    return bytes(result)


def main():
    data_dir = '/srv/nist/data'
    config_path = '/srv/nist/config.json'
    os.makedirs(data_dir, exist_ok=True)

    num_streams = 20
    bits_per_stream = 100000

    # Source 1: SHA-256 CTR (cryptographically strong PRNG)
    all_bits = []
    for i in range(num_streams):
        stream_bits = sha256_ctr_bits(seed_int=42 + i * 1000, num_bits=bits_per_stream)
        all_bits.extend(stream_bits)
    with open(os.path.join(data_dir, 'csprng.bin'), 'wb') as f:
        f.write(bits_to_bytes(all_bits))

    # Source 2: Periodic (random base of 5000 bits, repeated 20x per stream)
    all_bits = []
    for i in range(num_streams):
        stream_bits = periodic_bits(
            seed=7777 + i, base_length=5000, total_bits=bits_per_stream
        )
        all_bits.extend(stream_bits)
    with open(os.path.join(data_dir, 'periodic.bin'), 'wb') as f:
        f.write(bits_to_bytes(all_bits))

    # Source 3: Biased Bernoulli(0.47) - systematic bias towards 0
    all_bits = []
    for i in range(num_streams):
        stream_bits = biased_bits(seed=9999 + i, num_bits=bits_per_stream, p=0.47)
        all_bits.extend(stream_bits)
    with open(os.path.join(data_dir, 'biased.bin'), 'wb') as f:
        f.write(bits_to_bytes(all_bits))

    # Write configuration
    config = {
        "data_dir": data_dir,
        "stream_length_bits": bits_per_stream,
        "num_streams": num_streams,
        "significance_level": 0.01,
        "tests": {
            "frequency": {},
            "block_frequency": {"block_size": 128},
            "runs": {},
            "longest_run": {},
            "dft": {},
            "cumulative_sums": {"mode": "forward"},
            "approximate_entropy": {"m": 10}
        },
        "sources": ["csprng.bin", "periodic.bin", "biased.bin"]
    }
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print("Data generation complete.")
    for src in config["sources"]:
        path = os.path.join(data_dir, src)
        size = os.path.getsize(path)
        print(f"  {src}: {size} bytes ({size * 8} bits)")


if __name__ == '__main__':
    main()
