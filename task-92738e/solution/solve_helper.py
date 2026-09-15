#!/usr/bin/env python3

"""
ECDSA nonce-reuse key recovery from a multi-format signature corpus.

Pipeline:
  1. Query SQLite database for key/signature/challenge metadata
  2. Parse PEM SubjectPublicKeyInfo files to extract compressed EC public keys
  3. Parse DER-encoded signature files to extract (r, s) integer pairs
  4. Detect nonce reuse via shared r values per key
  5. Algebraic private key recovery from nonce-reuse pairs
  6. Sign challenge messages, output as JSON + DER
"""

import json
import os
import sqlite3
import base64
import hashlib
import hmac
from collections import defaultdict

# ===== secp256k1 curve parameters =====
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (Gx, Gy)


# ===== Modular arithmetic =====

def _egcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = _egcd(b % a, a)
    return g, y - (b // a) * x, x

def modinv(a, m):
    a = a % m
    g, x, _ = _egcd(a, m)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % m


# ===== EC point arithmetic =====

def point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if y1 != y2:
            return None
        lam = (3 * x1 * x1) * modinv(2 * y1, P) % P
    else:
        lam = (y2 - y1) * modinv(x2 - x1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)

def point_mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result

def compress_pubkey(point):
    x, y = point
    prefix = "02" if y % 2 == 0 else "03"
    return prefix + format(x, '064x')

def hex64(val):
    return format(val, '064x')


# ===== ASN.1 DER parsing =====

def parse_der_element(data, offset=0):
    """Parse one DER TLV element."""
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[offset:offset + n], 'big')
        offset += n
    value = data[offset:offset + length]
    return tag, value, offset + length

def parse_pem_pubkey(filepath):
    """Extract compressed EC public key hex from PEM SubjectPublicKeyInfo."""
    with open(filepath) as f:
        pem = f.read()
    # Decode base64 body
    b64 = ''.join(
        line.strip() for line in pem.split('\n')
        if line.strip() and not line.startswith('-----')
    )
    der = base64.b64decode(b64)

    # Parse: SEQUENCE { SEQUENCE { OID, OID }, BIT STRING }
    tag, seq_val, _ = parse_der_element(der, 0)
    assert tag == 0x30
    # Skip AlgorithmIdentifier SEQUENCE
    tag, _, next_off = parse_der_element(seq_val, 0)
    assert tag == 0x30
    # BIT STRING
    tag, bit_val, _ = parse_der_element(seq_val, next_off)
    assert tag == 0x03
    assert bit_val[0] == 0  # unused bits
    return bit_val[1:].hex()

def parse_der_signature(filepath):
    """Extract (r_int, s_int) from a DER-encoded ECDSA signature file."""
    with open(filepath, 'rb') as f:
        data = f.read()
    tag, seq_val, _ = parse_der_element(data, 0)
    assert tag == 0x30
    tag, r_bytes, next_off = parse_der_element(seq_val, 0)
    assert tag == 0x02
    tag, s_bytes, _ = parse_der_element(seq_val, next_off)
    assert tag == 0x02
    return int.from_bytes(r_bytes, 'big'), int.from_bytes(s_bytes, 'big')


# ===== DER encoding (for output) =====

def der_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    else:
        return bytes([0x82, (length >> 8) & 0xff, length & 0xff])

def der_integer(value):
    if value == 0:
        return b'\x02\x01\x00'
    byte_len = (value.bit_length() + 7) // 8
    b = value.to_bytes(byte_len, 'big')
    if b[0] & 0x80:
        b = b'\x00' + b
    return b'\x02' + der_length(len(b)) + b

def encode_der_signature(r, s):
    content = der_integer(r) + der_integer(s)
    return b'\x30' + der_length(len(content)) + content


# ===== ECDSA operations =====

def sign_ecdsa(d, z, k):
    """Sign with explicit nonce k, return (r, s) with low-s normalization."""
    R = point_mul(k, G)
    r = R[0] % N
    s = (modinv(k, N) * (z + r * d)) % N
    if s > N // 2:
        s = N - s
    return (r, s)

def verify_ecdsa(pubkey_point, z, r, s):
    w = modinv(s, N)
    u1 = (z * w) % N
    u2 = (r * w) % N
    pt = point_add(point_mul(u1, G), point_mul(u2, pubkey_point))
    return pt is not None and pt[0] % N == r

def recover_key_from_pair(z1, r, s1, z2, s2):
    """Recover private key from two signatures sharing the same nonce."""
    candidates = []
    for s1_try in [s1, N - s1]:
        for s2_try in [s2, N - s2]:
            ds = (s1_try - s2_try) % N
            if ds == 0:
                continue
            dz = (z1 - z2) % N
            k = (dz * modinv(ds, N)) % N
            if k == 0:
                continue
            d = ((s1_try * k - z1) * modinv(r, N)) % N
            if d != 0:
                candidates.append(d)
    return candidates

def deterministic_nonce(d, z):
    h = hmac.new(d.to_bytes(32, 'big'), z.to_bytes(32, 'big'), hashlib.sha256).digest()
    return int.from_bytes(h, 'big') % (N - 1) + 1


# ===== Main =====

def main():
    # Step 1: Query SQLite database
    db = sqlite3.connect('/app/corpus.db')
    db.row_factory = sqlite3.Row

    keys = {row['key_id']: dict(row)
            for row in db.execute('SELECT * FROM ec_keys')}
    sigs = [dict(row)
            for row in db.execute('SELECT * FROM ecdsa_signatures ORDER BY sig_id')]
    challenges = [dict(row)
                  for row in db.execute('SELECT * FROM signing_challenges ORDER BY challenge_id')]
    db.close()

    print(f"Loaded {len(keys)} keys, {len(sigs)} signatures, {len(challenges)} challenges from SQLite")

    # Step 2: Parse PEM files to get compressed public key hex per key_id
    key_pubhex = {}
    for key_id, key_info in keys.items():
        pem_path = f"/app/keys/{key_info['pem_file']}"
        pubhex = parse_pem_pubkey(pem_path)
        key_pubhex[key_id] = pubhex
        print(f"  Key {key_id} ({key_info['alias']}): {pubhex[:20]}...")

    # Step 3: Parse DER signature files to get (r, s) per sig
    sig_data = []
    for sig_info in sigs:
        der_path = f"/app/sigs/{sig_info['der_file']}"
        r, s = parse_der_signature(der_path)
        sig_data.append({
            'sig_id': sig_info['sig_id'],
            'key_id': sig_info['key_id'],
            'message_hash': sig_info['message_hash'],
            'r': r,
            's': s,
            'r_hex': hex64(r),
        })

    print(f"Parsed {len(sig_data)} DER signatures")

    # Step 4: Group by (key_id, r) to detect nonce reuse
    groups = defaultdict(list)
    for sd in sig_data:
        groups[(sd['key_id'], sd['r_hex'])].append(sd)

    reuse_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    print(f"Found {len(reuse_groups)} nonce-reuse groups")

    # Step 5: Recover private keys
    recovered_keys = {}  # key_id -> private key int
    for (key_id, _), sig_list in reuse_groups.items():
        if key_id in recovered_keys:
            continue

        s0 = sig_list[0]
        s1 = sig_list[1]
        r = s0['r']
        z1 = int(s0['message_hash'], 16)
        z2 = int(s1['message_hash'], 16)

        candidates = recover_key_from_pair(z1, r, s0['s'], z2, s1['s'])

        target_pubhex = key_pubhex[key_id]
        for d in candidates:
            pk = point_mul(d, G)
            if compress_pubkey(pk) == target_pubhex:
                recovered_keys[key_id] = d
                print(f"  Recovered key {key_id}: {hex64(d)[:20]}...")
                break

    print(f"Recovered {len(recovered_keys)} private keys")
    assert len(recovered_keys) == len(keys), "Failed to recover all keys"

    # Step 6: Verify recovered keys against existing signatures
    for sd in sig_data:
        d = recovered_keys[sd['key_id']]
        z = int(sd['message_hash'], 16)
        pk_point = point_mul(d, G)
        assert verify_ecdsa(pk_point, z, sd['r'], sd['s']), \
            f"Verification failed for sig {sd['sig_id']}"

    # Step 7: Sign challenges and produce output
    os.makedirs('/app/output', exist_ok=True)
    results = []

    for ch in challenges:
        key_id = ch['key_id']
        msg_hash = ch['message_hash']
        z = int(msg_hash, 16)
        d = recovered_keys[key_id]
        pem_file = keys[key_id]['pem_file']

        k = deterministic_nonce(d, z)
        r, s = sign_ecdsa(d, z, k)

        # Verify our own signature
        pk_point = point_mul(d, G)
        assert verify_ecdsa(pk_point, z, r, s), "Self-verification failed"

        # JSON result
        results.append({
            "key_pem_file": pem_file,
            "message_hash": msg_hash,
            "signature_r": hex64(r),
            "signature_s": hex64(s),
        })

        # DER output file
        der_bytes = encode_der_signature(r, s)
        der_path = f"/app/output/challenge_{ch['challenge_id']}.der"
        with open(der_path, 'wb') as f:
            f.write(der_bytes)
        print(f"  Wrote {der_path}")

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} results to /app/results.json")


if __name__ == '__main__':
    main()
