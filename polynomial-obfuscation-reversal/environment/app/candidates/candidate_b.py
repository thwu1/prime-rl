#!/usr/bin/env python3
"""
SEAT Transform Decryptor - Analysis B

Reverse engineering summary for libseat.so:
- Transform structure: alternating XOR mixing and GF(2^64) field multiplication
- Field polynomial: x^64 + x^4 + x^3 + x + 1 (reduction constant 0x1b)
- Constant pool at .rodata contains 7 uint64 values
- Operation order determined from call graph analysis

Pool constants:
  pool[0] = 0xA5A5A5A5A5A5A5A5
  pool[1] = 0xBADCAFE0DEADBEEF
  pool[2] = 0x1337FACE8BADF00D
  pool[3] = 0xFEEDFACEDEADC0DE
  pool[4] = 0x3C3C3C3C3C3C3C3C
  pool[5] = 0xDEADBEEFCAFEBABE
  pool[6] = 0x6969696969696969

Operation sequence (from register tracking):
  XOR pool[5] -> MUL pool[0] -> XOR pool[3] -> MUL pool[4] ->
  XOR pool[2] -> MUL pool[6] -> XOR pool[1]

Note: pool[2] and pool[3] are used in XOR positions between the
multiplication stages. The ordering was determined by tracking
which constants are loaded into rdi vs rsi before each call.
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

K0 = _E[5]
C0 = _E[0]
K1 = _E[3]   # pool[3] used as second XOR key
C1 = _E[4]
K2 = _E[2]   # pool[2] used as third XOR key
C2 = _E[6]
K3 = _E[1]


def gf2_64_mul(a, b):
    result = 0
    a = a & MASK64
    for i in range(64):
        if (b >> i) & 1:
            result ^= a
        carry = (a >> 63) & 1
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
    json.dump(results, open("/app/results_b.json", "w"), indent=2)
    print("Candidate B decryption results:")
    for i, (t, r) in enumerate(zip(targets, results)):
        print(f"  [{i}] {t} -> {r}")
