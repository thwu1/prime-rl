#!/usr/bin/env python3

"""Keygen for the VM-protected license validator.

Reverses the username hash and bytecode key-derivation algorithm
to produce valid license keys for arbitrary usernames.
"""

import sys

MAGIC  = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2 = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]
M = 0xFFFFFFFF


def hash_username(name):
    h = 0x5F3759DF
    for c in name:
        v = ord(c) & 0xFF
        h = (h ^ (v * 0x1337)) & M
        h = (h + 0xDEADBEEF) & M
        h = ((h << 7) | (h >> 25)) & M
        h = (h * 0x01000193) & M
    return h


def generate_key(username):
    seed = hash_username(username)
    groups = []
    for i in range(5):
        val = seed
        # Round 1
        val = ((val ^ MAGIC[i]) * PRIMES[i]) & M
        val = ((val >> 13) | (val << 19)) & M          # rotr 13
        val = (val ^ (val >> 16)) & M
        # Round 2
        val = ((val + ROUND2[i]) ^ seed) & M
        val = ((val << 7) | (val >> 25)) & M            # rotl 7
        val = (val * 0x5BD1E995) & M
        val = (val ^ (val >> 15)) & M
        groups.append(f"{val:08X}")
        # Chain seed for next group
        seed = ((seed ^ val) + MAGIC[i]) & M
        seed = ((seed >> 11) | (seed << 21)) & M        # rotr 11
        seed = (seed * 0x1B873593) & M
    return "-".join(groups)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <username>", file=sys.stderr)
        sys.exit(1)
    print(generate_key(sys.argv[1]))
