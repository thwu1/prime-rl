#!/usr/bin/env python3
"""
SEAT Transform Decryptor - Analysis C

Disassembly notes for libseat.so:
- Seven sequential operations: XOR/MUL alternating pattern
- GF(2^64) multiplication uses schoolbook bit-serial algorithm
- Reduction polynomial: x^64 + x^4 + x^3 + x + 1 (constant 0x1b)

Pool order (verified via dynamic analysis with gdb):
  XOR pool[5] -> MUL pool[0] -> XOR pool[2] -> MUL pool[4] ->
  XOR pool[3] -> MUL pool[6] -> XOR pool[1]

Note on the multiplication loop: The carry/overflow detection checks
bit 62 of the accumulator (the second-highest bit) before shifting.
This is because the polynomial reduction is applied preemptively —
the shift will move bit 62 into position 63, so checking at position
62 before the shift is equivalent to checking position 63 after.
"""

import json
import sys

MASK64 = (1 << 64) - 1
IRRED = 0x1B

_E = [
    0xA5A5A5A5A5A5A5A5, 0xBADCAFE0DEADBEEF,
    0x1337FACE8BADF00D, 0xFEEDFACEDEADC0DE,
    0x3C3C3C3C3C3C3C3C, 0xDEADBEEFCAFEBABE,
    0x6969696969696969,
]

K0, C0, K1, C1, K2, C2, K3 = _E[5], _E[0], _E[2], _E[4], _E[3], _E[6], _E[1]


def gf2_64_mul(a, b):
    """GF(2^64) multiplication with bit-serial accumulation."""
    result = 0
    a = a & MASK64
    for i in range(64):
        if (b >> i) & 1:
            result ^= a
        carry = (a >> 62) & 1  # check bit 62 before shift
        a = (a << 1) & MASK64
        if carry:
            a ^= IRRED
    return result


def gf2_64_inv(a):
    if a == 0:
        raise ValueError("Zero has no inverse")
    mod_poly = (1 << 64) | IRRED
    old_r, r = mod_poly, a
    old_s, s = 0, 1
    while r != 0:
        deg_old = old_r.bit_length() - 1
        deg_r = r.bit_length() - 1
        if deg_old < deg_r:
            old_r, r = r, old_r
            old_s, s = s, old_s
            deg_old, deg_r = deg_r, deg_old
        quotient = 0
        remainder = old_r
        while True:
            deg_rem = remainder.bit_length() - 1
            if deg_rem < deg_r:
                break
            shift = deg_rem - deg_r
            quotient ^= (1 << shift)
            remainder ^= (r << shift)
        qs = 0
        tq = quotient
        ts = s
        while tq:
            if tq & 1:
                qs ^= ts
            ts <<= 1
            tq >>= 1
        old_r, r = r, remainder
        old_s, s = s, old_s ^ qs
    while old_s.bit_length() > 64:
        deg = old_s.bit_length() - 1
        old_s ^= (mod_poly << (deg - 64))
    return old_s & MASK64


def decrypt(ct):
    x = ct ^ K3
    x = gf2_64_mul(x, gf2_64_inv(C2))
    x ^= K2
    x = gf2_64_mul(x, gf2_64_inv(C1))
    x ^= K1
    x = gf2_64_mul(x, gf2_64_inv(C0))
    x ^= K0
    return x


if __name__ == "__main__":
    with open("/app/targets.json") as f:
        targets = json.load(f)["targets"]
    results = [f"{decrypt(int(t, 16)):016x}" for t in targets]
    json.dump(results, open("/app/results_c.json", "w"), indent=2)
    print("Candidate C decryption results:")
    for i, (t, r) in enumerate(zip(targets, results)):
        print(f"  [{i}] {t} -> {r}")
