#!/usr/bin/env python3
"""
DSA Signature Forensics — Solution

Reads challenge data from crypto-native formats (PEM, SQLite, DER),
recovers three private keys from nonce generation vulnerabilities,
and forges DSA signatures in both DER and JSON formats.
"""

import base64
import hashlib
import json
import os
import sqlite3
import sys


# === DER/ASN.1 parsing ===

def parse_der_length(data, offset):
    if data[offset] < 0x80:
        return data[offset], offset + 1
    num_bytes = data[offset] & 0x7f
    offset += 1
    length = int.from_bytes(data[offset:offset + num_bytes], 'big')
    return length, offset + num_bytes


def parse_der_integer(data, offset):
    assert data[offset] == 0x02
    offset += 1
    length, offset = parse_der_length(data, offset)
    value = int.from_bytes(data[offset:offset + length], 'big')
    return value, offset + length


def parse_der_sequence_start(data, offset):
    assert data[offset] == 0x30
    offset += 1
    length, offset = parse_der_length(data, offset)
    return length, offset


def skip_der_element(data, offset):
    offset += 1
    length, offset = parse_der_length(data, offset)
    return offset + length


def parse_sig_der(data):
    _, offset = parse_der_sequence_start(data, 0)
    r, offset = parse_der_integer(data, offset)
    s, offset = parse_der_integer(data, offset)
    return r, s


def parse_pem_der(pem_text):
    lines = pem_text.strip().split('\n')
    b64_lines = []
    in_body = False
    for line in lines:
        if line.startswith('-----BEGIN'):
            in_body = True
            continue
        if line.startswith('-----END'):
            break
        if in_body:
            b64_lines.append(line.strip())
    return base64.b64decode(''.join(b64_lines))


def parse_dsa_params_pem(pem_text):
    der = parse_pem_der(pem_text)
    _, offset = parse_der_sequence_start(der, 0)
    p_val, offset = parse_der_integer(der, offset)
    q_val, offset = parse_der_integer(der, offset)
    g_val, offset = parse_der_integer(der, offset)
    return p_val, q_val, g_val


def parse_dsa_pubkey_pem(pem_text):
    der = parse_pem_der(pem_text)
    _, offset = parse_der_sequence_start(der, 0)
    offset_after_algo = skip_der_element(der, offset)
    assert der[offset_after_algo] == 0x03
    offset_after_algo += 1
    _, offset_bs = parse_der_length(der, offset_after_algo)
    assert der[offset_bs] == 0x00
    y_val, _ = parse_der_integer(der, offset_bs + 1)
    return y_val


# === DER/ASN.1 encoding ===

def der_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return b'\x81' + bytes([length])
    else:
        return b'\x82' + length.to_bytes(2, 'big')


def der_integer(value):
    if value == 0:
        return b'\x02\x01\x00'
    byte_len = (value.bit_length() + 7) // 8
    raw = value.to_bytes(byte_len, 'big')
    if raw[0] & 0x80:
        raw = b'\x00' + raw
    return b'\x02' + der_length(len(raw)) + raw


def der_sequence(contents):
    return b'\x30' + der_length(len(contents)) + contents


def make_pem(der_bytes, label):
    b64 = base64.b64encode(der_bytes).decode('ascii')
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


def make_sig_der(r_val, s_val):
    return der_sequence(der_integer(r_val) + der_integer(s_val))


def make_dsa_privkey_pem(x_val, y_val, p_val, q_val, g_val):
    inner = (der_integer(0) + der_integer(p_val) + der_integer(q_val) +
             der_integer(g_val) + der_integer(y_val) + der_integer(x_val))
    return make_pem(der_sequence(inner), "DSA PRIVATE KEY")


# === Crypto utilities ===

def modinv(a, m):
    a = a % m
    g_val, x = m, 0
    b, y = a, 1
    while b > 0:
        quo = g_val // b
        g_val, b = b, g_val - quo * b
        x, y = y, x - quo * y
    if g_val != 1:
        raise ValueError(f"No modular inverse for {a} mod {m}")
    return x % m


def sha1_int(msg):
    return int(hashlib.sha1(msg.encode("utf-8")).hexdigest(), 16)


def dsa_verify(h, r, s, y, p_val, q_val, g_val):
    if not (0 < r < q_val and 0 < s < q_val):
        return False
    w = modinv(s, q_val)
    u1 = (h * w) % q_val
    u2 = (r * w) % q_val
    v = (pow(g_val, u1, p_val) * pow(y, u2, p_val)) % p_val % q_val
    return v == r


def dsa_sign(h, x, k, p_val, q_val, g_val):
    r = pow(g_val, k, p_val) % q_val
    s = (modinv(k, q_val) * (h + x * r)) % q_val
    return r, s


# === Step 0: Load data from PEM, SQLite, and JSON ===

print("=== Loading challenge data ===")

# Parse DSA parameters from PEM
with open("/app/data/params.pem") as f:
    p, q, g = parse_dsa_params_pem(f.read())
print(f"DSA params loaded: p={p.bit_length()}-bit, q={q.bit_length()}-bit")

# Parse public keys from PEM
pub_keys = {}
for kid in ["alpha", "beta", "gamma"]:
    with open(f"/app/data/keys/{kid}.pub.pem") as f:
        pub_keys[kid] = parse_dsa_pubkey_pem(f.read())
print(f"Loaded {len(pub_keys)} public keys from PEM files")

# Load signatures from SQLite audit database
conn = sqlite3.connect("/app/data/audit.db")
cursor = conn.cursor()
cursor.execute("SELECT id, timestamp, message, signature_der FROM audit_log ORDER BY id")
rows = cursor.fetchall()
conn.close()

parsed_sigs = []
for db_id, ts, msg, sig_der_blob in rows:
    r, s = parse_sig_der(sig_der_blob)
    h = sha1_int(msg)
    parsed_sigs.append({"message": msg, "h": h, "r": r, "s": s})
print(f"Loaded {len(parsed_sigs)} signatures from SQLite (DER-decoded)")

# Load challenges
with open("/app/data/challenges.json") as f:
    challenges = json.load(f)


# === Step 1: Attribute each signature to a public key ===

print("\n=== Attributing signatures to keys ===")
key_groups = {kid: [] for kid in pub_keys}

for ps in parsed_sigs:
    for kid, y in pub_keys.items():
        if dsa_verify(ps["h"], ps["r"], ps["s"], y, p, q, g):
            key_groups[kid].append(ps)
            break

for kid in key_groups:
    print(f"  Key {kid}: {len(key_groups[kid])} signatures")


# === Step 2: Recover private keys ===

print("\n=== Recovering private keys ===")
recovered_keys = {}

for kid, sigs_for_key in key_groups.items():
    y = pub_keys[kid]

    # Try nonce reuse attack (matching r values)
    r_groups = {}
    for ps in sigs_for_key:
        r_groups.setdefault(ps["r"], []).append(ps)

    reused = {r_val: grp for r_val, grp in r_groups.items() if len(grp) >= 2}

    if reused:
        for r_val, group in reused.items():
            ps1, ps2 = group[0], group[1]
            ds = (ps1["s"] - ps2["s"]) % q
            if ds == 0:
                continue
            k = ((ps1["h"] - ps2["h"]) * modinv(ds, q)) % q
            x = ((ps1["s"] * k - ps1["h"]) * modinv(ps1["r"], q)) % q
            if pow(g, x, p) == y:
                recovered_keys[kid] = x
                print(f"  {kid}: recovered via nonce reuse")
                break
        continue

    # Try sequential nonce attack (k2 = k1 + 1)
    print(f"  {kid}: no nonce reuse, trying sequential nonce attack...")
    found = False
    for i in range(len(sigs_for_key)):
        if found:
            break
        for j in range(len(sigs_for_key)):
            if i == j:
                continue
            h1, r1, s1 = sigs_for_key[i]["h"], sigs_for_key[i]["r"], sigs_for_key[i]["s"]
            h2, r2, s2 = sigs_for_key[j]["h"], sigs_for_key[j]["r"], sigs_for_key[j]["s"]

            # From k2 = k1 + 1:
            #   k1*s1 = h1 + x*r1 (mod q)
            #   (k1+1)*s2 = h2 + x*r2 (mod q)
            # Eliminating x:
            numerator = (h2 * r1 - h1 * r2 - s2 * r1) % q
            denominator = (s2 * r1 - s1 * r2) % q
            if denominator == 0:
                continue
            try:
                k1 = (numerator * modinv(denominator, q)) % q
            except ValueError:
                continue
            x = ((s1 * k1 - h1) * modinv(r1, q)) % q
            if pow(g, x, p) == y:
                recovered_keys[kid] = x
                print(f"  {kid}: recovered via sequential nonce (pair {i},{j})")
                found = True
                break

if len(recovered_keys) != 3:
    missing = set(pub_keys.keys()) - set(recovered_keys.keys())
    print(f"ERROR: failed to recover: {missing}", file=sys.stderr)
    sys.exit(1)

print(f"\nAll 3 private keys recovered.")


# === Step 3: Generate output ===

print("\n=== Generating output ===")
os.makedirs("/app/results", exist_ok=True)

# Write PEM private key files
for kid in ["alpha", "beta", "gamma"]:
    x = recovered_keys[kid]
    y = pub_keys[kid]
    pem = make_dsa_privkey_pem(x, y, p, q, g)
    with open(f"/app/results/{kid}.priv.pem", "w") as f:
        f.write(pem)
    print(f"  Wrote {kid}.priv.pem")

# Forge signatures and write DER + JSON
forged_json = []
for ch in challenges:
    kid = ch["target_key"]
    msg = ch["message"]
    x = recovered_keys[kid]
    h = sha1_int(msg)

    # Deterministic nonce
    k_material = hashlib.sha256(f"{hex(x)}:{msg}".encode()).digest()
    k = int.from_bytes(k_material, "big") % (q - 2) + 1

    r, s = dsa_sign(h, x, k, p, q, g)
    assert dsa_verify(h, r, s, pub_keys[kid], p, q, g), \
        f"Self-verification failed for challenge {ch['challenge_id']}"

    # Write DER file
    sig_der = make_sig_der(r, s)
    with open(f"/app/results/forged_{ch['challenge_id']}.der", "wb") as f:
        f.write(sig_der)

    forged_json.append({
        "challenge_id": ch["challenge_id"],
        "r": hex(r),
        "s": hex(s),
    })
    print(f"  Challenge {ch['challenge_id']}: forged for key {kid}")

# Write results.json
results = {
    "recovered_private_keys": {kid: hex(x) for kid, x in recovered_keys.items()},
    "forged_signatures": forged_json,
}
with open("/app/results/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nAll results written to /app/results/")
