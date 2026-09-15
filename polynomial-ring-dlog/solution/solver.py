#!/usr/bin/env python3

"""
Solver for the CryptoExchange pcap challenge.

Pipeline:
  1. Read tshark follow output from /tmp/stream_raw.txt
  2. Parse CryptoExchange TLV protocol messages
  3. Factor the GF(2) modulus polynomial (distinct-degree + Cantor-Zassenhaus)
  4. Solve DLP in each factor field via baby-step giant-step
  5. Combine with CRT to recover private key
  6. Compute shared secret, write key material for openssl decryption
"""

import math
import struct
import sys


# ── Read tshark follow,tcp,raw output ──

def read_stream_data(path="/tmp/stream_raw.txt"):
    """Parse tshark 'follow,tcp,raw' output into raw bytes."""
    with open(path) as f:
        lines = f.readlines()

    hex_data = ''
    started = False
    for line in lines:
        s = line.strip()
        if s.startswith('===='):
            if started:
                break
            started = True
            continue
        if started and s:
            if s.startswith('Follow:') or s.startswith('Filter:') or s.startswith('Node '):
                continue
            clean = ''.join(c for c in s if c in '0123456789abcdefABCDEF')
            if clean:
                hex_data += clean.lower()

    return bytes.fromhex(hex_data)


# ── Parse CryptoExchange protocol ──

MAGIC = b'\xCE\xFF'

def parse_messages(data):
    """Parse TLV messages from raw protocol data."""
    messages = {}
    offset = 0
    while offset + 5 <= len(data):
        if data[offset:offset + 2] != MAGIC:
            offset += 1
            continue
        msg_type = data[offset + 2]
        length = struct.unpack('!H', data[offset + 3:offset + 5])[0]
        if offset + 5 + length > len(data):
            break
        payload = data[offset + 5:offset + 5 + length]
        messages[msg_type] = payload
        print(f"  type=0x{msg_type:02x}  len={length}")
        offset += 5 + length
    return messages


def extract_params(messages):
    """Extract crypto parameters from parsed messages."""
    # PARAMS (0x02): 9B modulus + 8B generator
    p = messages[0x02]
    modulus   = int.from_bytes(p[:9], 'big')
    generator = int.from_bytes(p[9:17], 'big')
    # PUBKEY_A (0x03): 8B
    pub_a = int.from_bytes(messages[0x03], 'big')
    # PUBKEY_B (0x04): 8B
    pub_b = int.from_bytes(messages[0x04], 'big')
    # ENCRYPTED (0x05): 16B IV + 4B ct_len + ciphertext
    e = messages[0x05]
    iv = e[:16]
    ct_len = struct.unpack('!I', e[16:20])[0]
    ciphertext = e[20:20 + ct_len]
    return modulus, generator, pub_a, pub_b, iv, ciphertext


# ── GF(2) polynomial arithmetic ──

def poly_degree(f):
    return -1 if f == 0 else f.bit_length() - 1

def poly_mul(f, g):
    result = 0
    while g:
        if g & 1:
            result ^= f
        f <<= 1
        g >>= 1
    return result

def poly_mod(f, g):
    dg = poly_degree(g)
    if dg < 0:
        raise ZeroDivisionError
    while True:
        df = poly_degree(f)
        if df < dg:
            return f
        f ^= g << (df - dg)

def poly_mulmod(f, g, m):
    return poly_mod(poly_mul(f, g), m)

def poly_powmod(base, exp, mod):
    result = 1
    base = poly_mod(base, mod)
    while exp > 0:
        if exp & 1:
            result = poly_mulmod(result, base, mod)
        exp >>= 1
        base = poly_mulmod(base, base, mod)
    return result

def poly_gcd(a, b):
    while b:
        a, b = b, poly_mod(a, b)
    return a

def poly_div_exact(f, g):
    dg = poly_degree(g)
    result = 0
    while poly_degree(f) >= dg:
        shift = poly_degree(f) - dg
        result ^= (1 << shift)
        f ^= (g << shift)
    assert f == 0, "not exact division"
    return result


# ── Factoring over GF(2) ──

def split_equal_degree(f, d):
    if poly_degree(f) == d:
        return [f]

    import random
    rng = random.Random(12345)
    factors, stack = [], [f]

    while stack:
        g = stack.pop()
        if poly_degree(g) == d:
            factors.append(g)
            continue
        if poly_degree(g) == 0:
            continue

        for _ in range(200):
            r = rng.randint(1, (1 << poly_degree(g)) - 1)
            t, ri = r, r
            for _ in range(d - 1):
                ri = poly_powmod(ri, 2, g)
                t ^= ri
            h = poly_gcd(t, g)
            if h != 1 and h != g:
                stack.append(h)
                stack.append(poly_div_exact(g, h))
                break
        else:
            factors.append(g)

    return factors


def factor_gf2(f):
    """Distinct-degree + equal-degree factorization over GF(2)."""
    factors = []
    remaining = f
    h = 2  # x

    for i in range(1, poly_degree(f) // 2 + 1):
        h = poly_powmod(h, 2, remaining)
        g = poly_gcd(remaining, h ^ 2)  # gcd(f, x^(2^i) + x)
        if g != 1:
            for fac in split_equal_degree(g, i):
                while poly_mod(remaining, fac) == 0:
                    factors.append(fac)
                    remaining = poly_div_exact(remaining, fac)
        if poly_degree(remaining) == 0:
            break

    if poly_degree(remaining) > 0:
        factors.append(remaining)
    return factors


# ── Baby-step giant-step DLP in GF(2^d) ──

def bsgs(base, target, mod, order):
    m = int(math.isqrt(order)) + 1

    table = {}
    power = 1
    for j in range(m):
        table[power] = j
        power = poly_mulmod(power, base, mod)

    inv_factor = poly_powmod(base, order - m, mod)
    gamma = target
    for i in range(m):
        if gamma in table:
            return (i * m + table[gamma]) % order
        gamma = poly_mulmod(gamma, inv_factor, mod)

    # brute-force fallback
    power = 1
    for x in range(order):
        if power == target:
            return x
        power = poly_mulmod(power, base, mod)
    return None


# ── CRT ──

def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x

def crt(remainders, moduli):
    r, m = remainders[0], moduli[0]
    for i in range(1, len(remainders)):
        r2, m2 = remainders[i], moduli[i]
        g, p, _ = extended_gcd(m, m2)
        lcm = m * m2 // g
        r = (r + m * ((r2 - r) // g) * p) % lcm
        m = lcm
    return r % m


# ── Main ──

def main():
    print("[*] Reading tshark stream data...")
    raw_data = read_stream_data()
    print(f"[*] Got {len(raw_data)} bytes of protocol data")

    print("[*] Parsing CryptoExchange messages...")
    messages = parse_messages(raw_data)
    modulus, generator, pub_a, pub_b, iv, ciphertext = extract_params(messages)

    print(f"\n[*] Modulus:   {hex(modulus)} (degree {poly_degree(modulus)})")
    print(f"[*] Generator: {hex(generator)}")
    print(f"[*] Public A:  {hex(pub_a)}")
    print(f"[*] Public B:  {hex(pub_b)}")
    print(f"[*] IV:        {iv.hex()}")
    print(f"[*] Ciphertext: {len(ciphertext)} bytes")

    # Factor modulus
    print("\n[*] Factoring modulus polynomial over GF(2)...")
    factors = factor_gf2(modulus)
    print(f"[*] {len(factors)} irreducible factors:")
    for f in factors:
        print(f"    deg {poly_degree(f):2d}: {hex(f)}")

    # Solve DLP in each factor field
    print("\n[*] Solving DLP in factor fields (BSGS)...")
    dlogs, orders = [], []
    for fac in factors:
        d = poly_degree(fac)
        order = 2**d - 1
        g_red = poly_mod(generator, fac)
        a_red = poly_mod(pub_a, fac)
        a_i = bsgs(g_red, a_red, fac, order)
        assert a_i is not None, f"DLP failed for degree-{d} factor"
        print(f"    GF(2^{d:2d}): a = {a_i} (mod {order})")
        dlogs.append(a_i)
        orders.append(order)

    # CRT
    private_a = crt(dlogs, orders)
    print(f"\n[*] Recovered private key: {hex(private_a)}")

    # Verify
    check = poly_powmod(generator, private_a, modulus)
    print(f"[*] Verification g^a mod f: {hex(check)}")
    print(f"[*] Expected pub_A:         {hex(pub_a)}")
    assert check == pub_a, "Private key recovery FAILED"
    print("[*] Private key verified!")

    # Compute shared secret
    shared = poly_powmod(pub_b, private_a, modulus)
    print(f"[*] Shared secret: {hex(shared)}")

    # Write key material for openssl (called from solve.sh)
    shared_bytes = shared.to_bytes((shared.bit_length() + 7) // 8, 'big')
    with open('/tmp/shared_secret.bin', 'wb') as f:
        f.write(shared_bytes)
    with open('/tmp/iv.hex', 'w') as f:
        f.write(iv.hex())
    with open('/tmp/ciphertext.bin', 'wb') as f:
        f.write(ciphertext)

    print("\n[*] Key material written to /tmp/")
    print("[*] solve.sh will derive AES key and decrypt with openssl")


if __name__ == "__main__":
    main()
