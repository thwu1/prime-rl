#!/usr/bin/env python3
"""

Polynomial MAC forgery via nonce-reuse attack.
Uses data extracted by solve.sh from tshark, sqlite3, and objdump.
"""

import struct
import re
import os


# ===== Data loading from tool outputs =====

def load_target():
    """Load target ciphertext and nonce from sqlite3 query output."""
    with open('/tmp/target_ct.txt') as f:
        ct_hex = f.read().strip()
    with open('/tmp/target_nonce.txt') as f:
        nonce_hex = f.read().strip()
    return ct_hex, nonce_hex


def load_messages():
    """Parse protocol v2 messages from tshark-extracted PCAP payloads."""
    messages = []
    with open('/tmp/pcap_payloads.txt') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = bytes.fromhex(line.replace(':', ''))
            if len(raw) < 20:
                continue
            version = raw[0]
            if version != 0x02:
                continue
            msg_id = struct.unpack('>H', raw[1:3])[0]
            nonce_hex = raw[3:11].hex()
            ct_hex = raw[11:-8].hex()
            tag_hex = raw[-8:].hex()
            messages.append({
                'msg_id': msg_id,
                'nonce_hex': nonce_hex,
                'ct_hex': ct_hex,
                'tag_hex': tag_hex,
            })
    return messages


def find_reduction_polynomial():
    """Extract GF(2^64) reduction polynomial from objdump disassembly."""
    with open('/tmp/mac_disasm.txt') as f:
        disasm = f.read()

    in_func = False
    candidates = []
    for line in disasm.split('\n'):
        if '<gf64_multiply>' in line:
            in_func = True
            continue
        if in_func:
            stripped = line.strip()
            if stripped == '':
                break
            # Look for immediate operand in xor or mov instruction
            m = re.search(r'\$0x([0-9a-f]+)', line)
            if m:
                val = int(m.group(1), 16)
                if 1 < val < 0x10000 and val not in (0x3f, 0x40, 64):
                    candidates.append(val)

    if candidates:
        return candidates[0]
    print("WARNING: Could not extract reduction polynomial, using fallback")
    return 0x1b


# ===== GF(2^64) Arithmetic =====

REDUCTION = None


def gf64_mul(a, b):
    result = 0
    mask = (1 << 64) - 1
    for _ in range(64):
        if b & 1:
            result ^= a
        b >>= 1
        carry = a >> 63
        a = (a << 1) & mask
        if carry:
            a ^= REDUCTION
    return result


def gf64_pow(a, exp):
    result = 1
    base = a
    while exp > 0:
        if exp & 1:
            result = gf64_mul(result, base)
        base = gf64_mul(base, base)
        exp >>= 1
    return result


def gf64_inv(a):
    """Multiplicative inverse via Fermat's little theorem: a^(2^64-2)."""
    return gf64_pow(a, (1 << 64) - 2)


# ===== Polynomial arithmetic over GF(2^64)[x] =====
# Coefficients stored lowest degree first: [a0, a1, ..., an] = a0 + a1*x + ... + an*x^n

def poly_strip(p):
    p = list(p)
    while len(p) > 1 and p[-1] == 0:
        p.pop()
    return p


def poly_scale(p, c):
    return poly_strip([gf64_mul(x, c) for x in p])


def poly_divmod(a, b):
    """Returns remainder of a divided by b."""
    b = poly_strip(b)
    a = list(a)
    db = len(b) - 1
    lead_inv = gf64_inv(b[-1])
    while True:
        a = poly_strip(a)
        da = len(a) - 1
        if da < db or a == [0]:
            break
        coeff = gf64_mul(a[da], lead_inv)
        shift = da - db
        for i in range(len(b)):
            a[i + shift] ^= gf64_mul(b[i], coeff)
    return poly_strip(a)


def poly_gcd(a, b):
    a = poly_strip(a)
    b = poly_strip(b)
    while poly_strip(b) != [0]:
        r = poly_divmod(a, b)
        a, b = b, r
    a = poly_strip(a)
    if a[-1] != 0:
        inv = gf64_inv(a[-1])
        a = poly_scale(a, inv)
    return a


def ct_to_blocks(ct_hex):
    ct = bytes.fromhex(ct_hex)
    blocks = []
    for i in range(0, len(ct), 8):
        blocks.append(int.from_bytes(ct[i:i + 8], 'big'))
    return blocks


def build_diff_poly(msg_a, msg_b):
    """
    Build polynomial P(x) such that P(H) = 0 from two messages sharing a nonce.

    MAC_a XOR MAC_b = sum_i (block_a[i] XOR block_b[i]) * H^(n-i)
    """
    blocks_a = ct_to_blocks(msg_a['ct_hex'])
    blocks_b = ct_to_blocks(msg_b['ct_hex'])
    tag_a = int(msg_a['tag_hex'], 16)
    tag_b = int(msg_b['tag_hex'], 16)

    n = len(blocks_a)
    # Coefficients stored lowest-degree first
    coeffs = [0] * (n + 1)
    coeffs[0] = tag_a ^ tag_b  # constant term
    for i in range(n):
        coeffs[n - i] = blocks_a[i] ^ blocks_b[i]
    return poly_strip(coeffs)


# ===== Main attack =====

def main():
    global REDUCTION

    print("=== Step 1: Loading target from SQLite query output ===")
    target_ct_hex, target_nonce_hex = load_target()
    print(f"Target CT: {target_ct_hex[:24]}...")
    print(f"Target nonce: {target_nonce_hex}")

    print("\n=== Step 2: Parsing protocol messages from tshark output ===")
    messages = load_messages()
    print(f"Extracted {len(messages)} protocol v2 messages")
    for msg in messages:
        print(f"  msg_id={msg['msg_id']} nonce={msg['nonce_hex']} "
              f"ct_len={len(msg['ct_hex']) // 2}")

    print("\n=== Step 3: Extracting reduction polynomial from disassembly ===")
    REDUCTION = find_reduction_polynomial()
    print(f"Reduction polynomial: 0x{REDUCTION:x}")

    print("\n=== Step 4: Identifying nonce-reused messages ===")
    reused = [m for m in messages if m['nonce_hex'] == target_nonce_hex]
    print(f"Found {len(reused)} messages sharing target nonce")

    if len(reused) < 2:
        print("ERROR: need >= 2 messages with same nonce for attack")
        return

    print("\n=== Step 5: Recovering H via polynomial GCD ===")
    p01 = build_diff_poly(reused[0], reused[1])
    p02 = build_diff_poly(reused[0], reused[2])

    g = poly_gcd(p01, p02)
    deg = len(g) - 1
    print(f"GCD degree: {deg}")

    if deg != 1:
        print(f"ERROR: expected degree 1, got {deg}")
        return

    # g = [g0, 1] means g(x) = x + g0, root is x = g0
    H = gf64_mul(g[0], gf64_inv(g[1]))
    print(f"Recovered H: {H:016x}")

    print("\n=== Step 6: Recovering S (one-time mask) ===")
    blocks_0 = ct_to_blocks(reused[0]['ct_hex'])
    acc = 0
    for block in blocks_0:
        acc = gf64_mul(acc ^ block, H)
    S = acc ^ int(reused[0]['tag_hex'], 16)
    print(f"Recovered S: {S:016x}")

    print("\n=== Step 7: Forging tag for target ciphertext ===")
    target_blocks = ct_to_blocks(target_ct_hex)
    acc = 0
    for block in target_blocks:
        acc = gf64_mul(acc ^ block, H)
    forged = acc ^ S
    forged_hex = format(forged, '016x')
    print(f"Forged tag: {forged_hex}")

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/forged_tag.txt', 'w') as f:
        f.write(forged_hex)
    print("\nWritten to /app/output/forged_tag.txt")


if __name__ == '__main__':
    main()
