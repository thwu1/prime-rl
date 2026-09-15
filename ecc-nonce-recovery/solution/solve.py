#!/usr/bin/env python3

"""
Solution: ECC Signing Service Security Audit

1. Evaluate all six signatures for vulnerabilities (nonce reuse).
2. Determine ECRDSA hash endianness convention (ISO vs RFC) for each ECRDSA sig.
3. Recover the private key via cross-algorithm nonce reuse (ECDSA-ECGDSA quadratic).
4. Construct PEM key files using the cryptography library.
5. Produce DER-encoded signature using OpenSSL CLI.
"""

import hashlib
import json
import subprocess
import sys

# ── Load challenge data ─────────────────────────────────────────────
with open("/app/challenge_data.json") as f:
    data = json.load(f)

curve = data["curve"]
p = int(curve["p"], 16)
a_coeff = int(curve["a"], 16)
n = int(curve["n"], 16)
Gx = int(curve["Gx"], 16)
Gy = int(curve["Gy"], 16)

QX = int(data["public_keys"]["Q"]["x"], 16)
QY = int(data["public_keys"]["Q"]["y"], 16)
QEX = int(data["public_keys"]["Q_ecgdsa"]["x"], 16)
QEY = int(data["public_keys"]["Q_ecgdsa"]["y"], 16)


# ── EC point arithmetic ─────────────────────────────────────────────
def modinv_p(val):
    return pow(val, p - 2, p)

def modinv_n(val):
    return pow(val, n - 2, n)

class ECPoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def is_inf(self):
        return self.x is None
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
    def __add__(self, other):
        if self.is_inf(): return other
        if other.is_inf(): return self
        if self.x == other.x:
            if (self.y + other.y) % p == 0:
                return ECPoint(None, None)
            lam = (3 * self.x * self.x + a_coeff) * modinv_p(2 * self.y) % p
        else:
            lam = (other.y - self.y) * modinv_p((other.x - self.x) % p) % p
        x3 = (lam * lam - self.x - other.x) % p
        y3 = (lam * (self.x - x3) - self.y) % p
        return ECPoint(x3, y3)
    def __rmul__(self, scalar):
        result = ECPoint(None, None)
        addend = ECPoint(self.x, self.y)
        k = scalar % n
        while k:
            if k & 1: result = result + addend
            addend = addend + addend
            k >>= 1
        return result

G = ECPoint(Gx, Gy)
Q_PUB = ECPoint(QX, QY)
Q_ECGDSA = ECPoint(QEX, QEY)


# ── Helper functions ────────────────────────────────────────────────
def sha256_int(msg):
    h = hashlib.sha256(msg.encode("utf-8")).digest()
    return int.from_bytes(h, "big") % n

def sha256_bytes(msg):
    return hashlib.sha256(msg.encode("utf-8")).digest()

def ecdsa_verify(msg, r, s, Q_pub):
    e = sha256_int(msg)
    s_inv = modinv_n(s)
    u = (e * s_inv) % n
    v = (r * s_inv) % n
    W = (u * G) + (v * Q_pub)
    return not W.is_inf() and W.x % n == r

def ecgdsa_verify(msg, r, s, Q_ecgdsa_pub):
    h = sha256_bytes(msg)
    e_raw = int.from_bytes(h, "big") % n
    r_inv = modinv_n(r)
    u = (e_raw * r_inv) % n
    v = (s * r_inv) % n
    W = (u * G) + (v * Q_ecgdsa_pub)
    return not W.is_inf() and W.x % n == r

def ecrdsa_verify(msg, r, s, Q_pub, use_rfc=False):
    h = sha256_bytes(msg)
    if use_rfc:
        h = h[::-1]
    e_raw = int.from_bytes(h, "big") % n
    if e_raw == 0:
        e_raw = 1
    v = modinv_n(e_raw)
    z1 = (s * v) % n
    z2 = ((-r) * v) % n
    W = (z1 * G) + (z2 * Q_pub)
    return not W.is_inf() and W.x % n == r

def tonelli_shanks(val, mod):
    if val == 0:
        return 0
    if pow(val, (mod - 1) // 2, mod) != 1:
        return None
    Q_val = mod - 1
    S = 0
    while Q_val % 2 == 0:
        Q_val //= 2
        S += 1
    z = 2
    while pow(z, (mod - 1) // 2, mod) != mod - 1:
        z += 1
    M = S
    c = pow(z, Q_val, mod)
    t = pow(val, Q_val, mod)
    R = pow(val, (Q_val + 1) // 2, mod)
    while True:
        if t == 1:
            return R
        i = 1
        temp = (t * t) % mod
        while temp != 1:
            temp = (temp * temp) % mod
            i += 1
        b = pow(c, 1 << (M - i - 1), mod)
        M = i
        c = (b * b) % mod
        t = (t * c) % mod
        R = (R * b) % mod


# ── Step 1: Scan for nonce reuse ────────────────────────────────────
print("=== Step 1: Scanning for nonce reuse (matching r values) ===")
sigs = data["signatures"]
nonce_pair = None
for i in range(len(sigs)):
    for j in range(i + 1, len(sigs)):
        ri = int(sigs[i]["r"], 16)
        rj = int(sigs[j]["r"], 16)
        if ri == rj:
            nonce_pair = (i, j)
            print(f"  Nonce reuse found: sig {i} ({sigs[i]['algorithm']}) "
                  f"<-> sig {j} ({sigs[j]['algorithm']})")
            break
    if nonce_pair:
        break

assert nonce_pair is not None, "No nonce reuse found!"


# ── Step 2: Evaluate ECRDSA conventions ─────────────────────────────
print("\n=== Step 2: Determining ECRDSA hash conventions ===")
ecrdsa_conventions = {}
for sig in sigs:
    if sig["algorithm"] != "ECRDSA":
        continue
    idx = sig["index"]
    r_val = int(sig["r"], 16)
    s_val = int(sig["s"], 16)
    msg = sig["message"]

    iso_ok = ecrdsa_verify(msg, r_val, s_val, Q_PUB, use_rfc=False)
    rfc_ok = ecrdsa_verify(msg, r_val, s_val, Q_PUB, use_rfc=True)

    if iso_ok and not rfc_ok:
        ecrdsa_conventions[idx] = "iso"
    elif rfc_ok and not iso_ok:
        ecrdsa_conventions[idx] = "rfc"
    else:
        ecrdsa_conventions[idx] = "ambiguous"
    print(f"  Sig {idx}: ISO={iso_ok}, RFC={rfc_ok} => {ecrdsa_conventions[idx]}")


# ── Step 3: Verify all non-reused signatures ────────────────────────
print("\n=== Step 3: Verifying all signatures ===")
for sig in sigs:
    idx = sig["index"]
    r_val = int(sig["r"], 16)
    s_val = int(sig["s"], 16)
    msg = sig["message"]
    alg = sig["algorithm"]

    if alg == "ECDSA":
        ok = ecdsa_verify(msg, r_val, s_val, Q_PUB)
    elif alg == "ECGDSA":
        ok = ecgdsa_verify(msg, r_val, s_val, Q_ECGDSA)
    elif alg == "ECRDSA":
        conv = ecrdsa_conventions.get(idx, "iso")
        ok = ecrdsa_verify(msg, r_val, s_val, Q_PUB, use_rfc=(conv == "rfc"))
    else:
        ok = False
    print(f"  Sig {idx} ({alg}): {'VALID' if ok else 'INVALID'}")


# ── Step 4: Recover private key via cross-algorithm nonce reuse ─────
print("\n=== Step 4: Recovering private key ===")
idx_a, idx_b = nonce_pair
sig_a = sigs[idx_a]
sig_b = sigs[idx_b]

# Determine ECDSA and ECGDSA roles
if sig_a["algorithm"] == "ECDSA" and sig_b["algorithm"] == "ECGDSA":
    ecdsa_sig, ecgdsa_sig = sig_a, sig_b
elif sig_a["algorithm"] == "ECGDSA" and sig_b["algorithm"] == "ECDSA":
    ecdsa_sig, ecgdsa_sig = sig_b, sig_a
else:
    sys.exit(f"Unexpected pair: {sig_a['algorithm']}, {sig_b['algorithm']}")

r = int(ecdsa_sig["r"], 16)
s1 = int(ecdsa_sig["s"], 16)
s3 = int(ecgdsa_sig["s"], 16)

# ECDSA: e1 = SHA256(m1) mod n
e1 = sha256_int(ecdsa_sig["message"])

# ECGDSA: e3' = -SHA256(m3) mod n
h3 = sha256_bytes(ecgdsa_sig["message"])
e3_raw = int.from_bytes(h3, "big") % n
e3_neg = (-e3_raw) % n

# Quadratic: A*x^2 + B*x + C = 0 (mod n)
# From ECDSA: k*s1 = e1 + x*r
# From ECGDSA: s3 = x*(k*r + e3_neg)
# Substituting k and simplifying:
A = (r * r) % n
B = (r * e1 + e3_neg * s1) % n
C = (-s1 * s3) % n

D = (B * B - 4 * A * C) % n
print(f"  Discriminant D = {hex(D)}")

sqrt_D = tonelli_shanks(D, n)
assert sqrt_D is not None, "No modular square root for discriminant!"
assert (sqrt_D * sqrt_D) % n == D, "Square root verification failed!"
print(f"  sqrt(D) = {hex(sqrt_D)}")

inv_2A = modinv_n((2 * A) % n)
x_cand1 = ((-B + sqrt_D) * inv_2A) % n
x_cand2 = ((-B - sqrt_D) * inv_2A) % n

x_recovered = None
for cand in [x_cand1, x_cand2]:
    Q_check = cand * G
    if Q_check == Q_PUB:
        x_recovered = cand
        break

assert x_recovered is not None, "Neither candidate matches public key!"
print(f"  Private key recovered: {hex(x_recovered)}")

# Verify against ECGDSA public key as well
x_inv = modinv_n(x_recovered)
Q_ecgdsa_check = x_inv * G
assert Q_ecgdsa_check == Q_ECGDSA, "Key does not match ECGDSA public key!"
print("  Cross-verified against Q_ecgdsa: OK")


# ── Step 5: Build audit report ──────────────────────────────────────
print("\n=== Step 5: Writing audit report ===")
findings = []
for sig in sigs:
    idx = sig["index"]
    if idx in nonce_pair:
        other = nonce_pair[1] if idx == nonce_pair[0] else nonce_pair[0]
        findings.append({
            "sig_index": idx,
            "status": "vulnerable",
            "vulnerability_type": "nonce_reuse",
            "details": f"Shares ephemeral nonce with signature {other} (matching r values)"
        })
    else:
        findings.append({
            "sig_index": idx,
            "status": "safe",
            "vulnerability_type": "none",
            "details": "No vulnerability detected"
        })

report = {
    "findings": findings,
    "ecrdsa_conventions": [
        {"sig_index": idx, "convention": conv}
        for idx, conv in sorted(ecrdsa_conventions.items())
    ],
    "exploited_pair": list(nonce_pair)
}

with open("/app/audit_report.json", "w") as f:
    json.dump(report, f, indent=2)
print("  audit_report.json written")


# ── Step 6: Create PEM key via cryptography library ─────────────────
print("\n=== Step 6: Creating PEM key files ===")
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private_key_obj = ec.derive_private_key(x_recovered, ec.SECP256R1())
pem_bytes = private_key_obj.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
with open("/app/recovered_key.pem", "wb") as f:
    f.write(pem_bytes)
print("  recovered_key.pem written")


# ── Step 7: Use OpenSSL CLI for public key and signature ────────────
print("\n=== Step 7: OpenSSL operations ===")

# Extract public key
result = subprocess.run(
    ["openssl", "pkey", "-in", "/app/recovered_key.pem",
     "-pubout", "-out", "/app/public_key.pem"],
    capture_output=True, text=True
)
assert result.returncode == 0, f"openssl pkey failed: {result.stderr}"
print("  public_key.pem derived via openssl pkey")

# Write challenge message to temp file
challenge_msg = data["challenge"]["message"]
msg_path = "/tmp/challenge_msg.bin"
with open(msg_path, "wb") as f:
    f.write(challenge_msg.encode("utf-8"))

# Sign with OpenSSL
result = subprocess.run(
    ["openssl", "dgst", "-sha256",
     "-sign", "/app/recovered_key.pem",
     "-out", "/app/challenge_sig.der",
     msg_path],
    capture_output=True, text=True
)
assert result.returncode == 0, f"openssl dgst -sign failed: {result.stderr}"
print("  challenge_sig.der produced via openssl dgst -sign")

# Self-verify with OpenSSL
result = subprocess.run(
    ["openssl", "dgst", "-sha256",
     "-verify", "/app/public_key.pem",
     "-signature", "/app/challenge_sig.der",
     msg_path],
    capture_output=True, text=True
)
print(f"  OpenSSL verification: {result.stdout.strip()}")
assert result.returncode == 0, f"OpenSSL self-verification failed: {result.stderr}"

print("\n=== Audit complete ===")
