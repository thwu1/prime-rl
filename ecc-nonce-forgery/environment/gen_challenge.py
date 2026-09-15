#!/usr/bin/env python3
"""
Generate cryptographic challenge data for the ECDSA nonce reuse + ECRDSA forgery task.
Uses the FRP256V1 curve (French national curve, designed by ANSSI).
"""
import hashlib
import json
import os

# FRP256V1 curve parameters (ANSSI - Agence nationale de la securite des systemes d'information)
p = 0xF1FD178C0B3AD58F10126DE8CE42435B3961ADBCABC8CA6DE8FCF353D86E9C03
a_coeff = 0xF1FD178C0B3AD58F10126DE8CE42435B3961ADBCABC8CA6DE8FCF353D86E9C00
b_coeff = 0xEE353FCA5428A9300D4ABA754A44C00FDFEC0C9AE4B1A1803075ED967B7BB73F
Gx = 0xB6B3D4C356C139EB31183D4749D423958C27D2DCAF98B70164C97A2DD98F5CFF
Gy = 0x6142E0F7C8B204911F9271F0F3ECEF8C2701C307E8E4C9E183115A1554062CFB
q = 0xF1FD178C0B3AD58F10126DE8CE42435B53DC67E140D2BF941FFDD459C6D655E1

def extended_gcd(a, b):
    old_r, r = a, b
    old_s, s = 1, 0
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
    return old_r, old_s

def modinv(val, mod):
    val = val % mod
    g, x = extended_gcd(val, mod)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % mod

INF = (None, None)

def point_add(P, Q):
    if P == INF:
        return Q
    if Q == INF:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return INF
        lam = (3 * x1 * x1 + a_coeff) * modinv(2 * y1, p) % p
    else:
        lam = (y2 - y1) * modinv((x2 - x1) % p, p) % p
    x3 = (lam * lam - x1 - x2) % p
    y3 = (lam * (x1 - x3) - y1) % p
    return (x3, y3)

def point_mul(k, P):
    R = INF
    Q = P
    while k > 0:
        if k & 1:
            R = point_add(R, Q)
        Q = point_add(Q, Q)
        k >>= 1
    return R

G = (Gx, Gy)

# Verify generator is on the curve
assert (Gy * Gy - Gx * Gx * Gx - a_coeff * Gx - b_coeff) % p == 0, "G not on curve"

# Derive private key deterministically from a seed
seed = hashlib.sha256(b"FRP256V1-ecdsa-nonce-reuse-challenge-v1-key").digest()
d = int.from_bytes(seed, 'big') % (q - 1) + 1

# Compute public key Q = dG
Q_pub = point_mul(d, G)
assert (Q_pub[1] ** 2 - Q_pub[0] ** 3 - a_coeff * Q_pub[0] - b_coeff) % p == 0, "Q not on curve"

# Messages to be signed
messages = [
    "Transfer 100 EUR to account FR7630001007941234567890185",
    "Authorize payment #4521 for supplier Airbus Defence",
    "Approve budget allocation Q3-2024 project ARTEMIS",
    "Release escrow funds reference E-20240315-DGSI",
    "Confirm wire transfer WR-8847261 to BNP Paribas",
    "Sign audit report AR-2024-Q1-FINAL for Cour des comptes",
]

# Derive nonces deterministically; indices 1 and 4 share the same nonce
def derive_nonce(label):
    h = hashlib.sha256(label.encode()).digest()
    return int.from_bytes(h, 'big') % (q - 1) + 1

shared_nonce = derive_nonce("shared-nonce-vuln-k")
nonces = [
    derive_nonce("nonce-0-alpha"),
    shared_nonce,
    derive_nonce("nonce-2-gamma"),
    derive_nonce("nonce-3-delta"),
    shared_nonce,  # REUSED nonce (same as index 1)
    derive_nonce("nonce-5-zeta"),
]

def ecdsa_sign(msg, priv_key, k):
    h = hashlib.sha256(msg.encode()).digest()
    e = int.from_bytes(h, 'big') % q
    W = point_mul(k, G)
    r = W[0] % q
    assert r != 0, "Bad r"
    s = (modinv(k, q) * (priv_key * r + e)) % q
    assert s != 0, "Bad s"
    return r, s

def ecdsa_verify(msg, r, s, pub):
    h = hashlib.sha256(msg.encode()).digest()
    e = int.from_bytes(h, 'big') % q
    s_inv = modinv(s, q)
    u1 = (e * s_inv) % q
    u2 = (r * s_inv) % q
    W = point_add(point_mul(u1, G), point_mul(u2, pub))
    if W == INF:
        return False
    return W[0] % q == r

# Generate and verify all signatures
sigs = []
for i in range(6):
    r, s = ecdsa_sign(messages[i], d, nonces[i])
    assert ecdsa_verify(messages[i], r, s, Q_pub), f"Signature {i} failed verification"
    sigs.append({
        "index": i,
        "message": messages[i],
        "r": format(r, '064x'),
        "s": format(s, '064x'),
    })

# Sanity: confirm nonce reuse is detectable (sigs 1 and 4 share r)
assert sigs[1]["r"] == sigs[4]["r"], "Nonce reuse not reflected in r values"
assert sigs[1]["s"] != sigs[4]["s"], "s values should differ"

challenge_message = "Emergency fund release authorization EFR-2024-CRITICAL-001"

os.makedirs("/app/challenge", exist_ok=True)
data = {
    "curve": {
        "name": "FRP256V1",
        "description": "French national elliptic curve (ANSSI)",
        "equation": "y^2 = x^3 + a*x + b (mod p)",
        "p": format(p, '064x'),
        "a": format(a_coeff, '064x'),
        "b": format(b_coeff, '064x'),
        "Gx": format(Gx, '064x'),
        "Gy": format(Gy, '064x'),
        "q": format(q, '064x'),
        "cofactor": 1,
    },
    "public_key": {
        "Qx": format(Q_pub[0], '064x'),
        "Qy": format(Q_pub[1], '064x'),
    },
    "ecdsa_signatures": sigs,
    "signature_scheme": "ECDSA with SHA-256",
    "challenge": {
        "message": challenge_message,
        "required_scheme": "ECRDSA",
        "hash_algorithm": "SHA-256",
        "variant": "RFC/GOST R 34.10-2012 (note: hash endianness handling differs from ISO 14888-3)",
    },
}

with open("/app/challenge/data.json", "w") as f:
    json.dump(data, f, indent=2)

print("Challenge data generated successfully.")
print(f"  Curve: FRP256V1")
print(f"  Signatures: {len(sigs)}")
print(f"  Nonce reuse: indices 1 and 4")
print(f"  Challenge: ECRDSA forgery")
