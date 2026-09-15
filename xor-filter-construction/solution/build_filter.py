#!/usr/bin/env python3

"""
Xor8 filter construction following /app/SPEC.md.
Reads keys from /app/data/keys.txt, builds the filter, writes output to /app/output/.
"""

import math
import os

MASK64 = 0xFFFFFFFFFFFFFFFF
MASK32 = 0xFFFFFFFF


def murmur64(h):
    h &= MASK64
    h ^= h >> 33
    h = (h * 0xFF51AFD7ED558CCD) & MASK64
    h ^= h >> 33
    h = (h * 0xC4CEB9FE1A85EC53) & MASK64
    h ^= h >> 33
    return h


def rotl64(x, r):
    return ((x << r) | (x >> (64 - r))) & MASK64


def fast_reduce(x, n):
    return (x * n) >> 32


def compute_hash_and_positions(key, seed, segment_length):
    h = murmur64((key + seed) & MASK64)
    fp = (h >> 56) & 0xFF
    r0 = h & MASK32
    r1 = rotl64(h, 21) & MASK32
    r2 = rotl64(h, 42) & MASK32
    h0 = fast_reduce(r0, segment_length)
    h1 = fast_reduce(r1, segment_length) + segment_length
    h2 = fast_reduce(r2, segment_length) + 2 * segment_length
    return h, fp, h0, h1, h2


def build_xor8(keys):
    n = len(keys)
    capacity = math.ceil(n * 1.23)
    rem = capacity % 3
    if rem != 0:
        capacity += 3 - rem
    segment_length = capacity // 3

    for attempt in range(1, 1001):
        seed = attempt

        # Phase 1: Map
        count = [0] * capacity
        xor_set = [0] * capacity

        for key in keys:
            h, fp, h0, h1, h2 = compute_hash_and_positions(
                key, seed, segment_length
            )
            count[h0] += 1
            count[h1] += 1
            count[h2] += 1
            xor_set[h0] ^= h
            xor_set[h1] ^= h
            xor_set[h2] ^= h

        # Phase 2: Peel
        queue = [i for i in range(capacity) if count[i] == 1]
        peel_order = []
        qi = 0
        while qi < len(queue):
            pos = queue[qi]
            qi += 1
            if count[pos] != 1:
                continue

            key_hash = xor_set[pos]
            fp = (key_hash >> 56) & 0xFF
            r0 = key_hash & MASK32
            r1 = rotl64(key_hash, 21) & MASK32
            r2 = rotl64(key_hash, 42) & MASK32
            kh0 = fast_reduce(r0, segment_length)
            kh1 = fast_reduce(r1, segment_length) + segment_length
            kh2 = fast_reduce(r2, segment_length) + 2 * segment_length

            peel_order.append((key_hash, pos))

            for p in (kh0, kh1, kh2):
                count[p] -= 1
                xor_set[p] ^= key_hash
                if count[p] == 1:
                    queue.append(p)

        if len(peel_order) == n:
            # Phase 3: Fill (reverse peel order)
            table = [0] * capacity
            for key_hash, lone_pos in reversed(peel_order):
                fp = (key_hash >> 56) & 0xFF
                r0 = key_hash & MASK32
                r1 = rotl64(key_hash, 21) & MASK32
                r2 = rotl64(key_hash, 42) & MASK32
                kh0 = fast_reduce(r0, segment_length)
                kh1 = fast_reduce(r1, segment_length) + segment_length
                kh2 = fast_reduce(r2, segment_length) + 2 * segment_length

                table[lone_pos] = fp ^ table[kh0] ^ table[kh1] ^ table[kh2]

            return table, seed, segment_length, attempt

    raise RuntimeError("Xor8 construction failed after 1000 seed attempts")


def main():
    with open("/app/data/keys.txt") as f:
        keys = [int(line.strip()) for line in f if line.strip()]

    print(f"Read {len(keys)} keys")

    table, seed, segment_length, attempts = build_xor8(keys)
    capacity = len(table)

    print(
        f"Filter built: seed={seed}, segment_length={segment_length}, "
        f"table_size={capacity}, attempts={attempts}"
    )

    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/filter.bin", "wb") as f:
        f.write(bytes(table))

    with open("/app/output/meta.txt", "w") as f:
        f.write(f"seed={seed}\n")
        f.write(f"segment_length={segment_length}\n")
        f.write(f"table_size={capacity}\n")
        f.write(f"attempts={attempts}\n")

    # Self-verification
    false_neg = 0
    for key in keys:
        h, fp, h0, h1, h2 = compute_hash_and_positions(
            key, seed, segment_length
        )
        if (table[h0] ^ table[h1] ^ table[h2]) != fp:
            false_neg += 1
    print(f"Self-check: {false_neg} false negatives")


if __name__ == "__main__":
    main()
