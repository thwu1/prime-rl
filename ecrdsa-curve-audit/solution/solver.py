#!/usr/bin/env python3

"""Solution for ECC Cross-Algorithm Signature Forensics task."""

import json
import hashlib
import sys
import subprocess


# ---------- EC math ----------

def egcd(a, b):
    x0, x1, y0, y1 = 1, 0, 0, 1
    while b != 0:
        qq, a, b = a // b, b, a % b
        x0, x1 = x1, x0 - qq * x1
        y0, y1 = y1, y0 - qq * y1
    return a, x0, y0


def modinv(a, m):
    g, x, _ = egcd(a % m, m)
    if g != 1:
        raise ValueError(f"No modular inverse for {a} mod {m}")
    return x % m


def ec_add(P, Q, a_coeff, p):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return None
        lam = ((3 * x1 * x1 + a_coeff) * modinv(2 * y1, p)) % p
    else:
        lam = ((y2 - y1) * modinv((x2 - x1) % p, p)) % p
    x3 = (lam * lam - x1 - x2) % p
    y3 = (lam * (x1 - x3) - y1) % p
    return (x3, y3)


def ec_mul(k, P, a_coeff, p):
    R = None
    Q = P
    while k > 0:
        if k & 1:
            R = ec_add(R, Q, a_coeff, p)
        Q = ec_add(Q, Q, a_coeff, p)
        k >>= 1
    return R


def sha256_str(msg):
    return hashlib.sha256(msg.encode('utf-8')).digest()


# ---------- Load challenge data ----------

with open("/challenge/curve_params.json") as f:
    cp = json.load(f)
p = int(cp["p"], 16)
a_coeff = int(cp["a"], 16)
b_coeff = int(cp["b"], 16)
Gx = int(cp["Gx"], 16)
Gy = int(cp["Gy"], 16)
order = int(cp["order"], 16)
G = (Gx, Gy)

with open("/challenge/captures.json") as f:
    cap = json.load(f)
Qx = int(cap["public_key"]["Qx"], 16)
Qy = int(cap["public_key"]["Qy"], 16)
Q = (Qx, Qy)

with open("/challenge/challenge_message.txt") as f:
    challenge_msg = f.read().strip()


# ---------- Step 1: Identify the curve ----------

KNOWN_PRIMES = {
    0xf1fd178c0b3ad58f10126de8ce42435b3961adbcabc8ca6de8fcf353d86e9c03: "FRP256V1",
    0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff: "SECP256R1",
    0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2f: "SECP256K1",
    0xa9fb57dba1eea9bc3e660a909d838d726e3bf623d52620282013481d1f6e5377: "BRAINPOOLP256R1",
}
curve_name = KNOWN_PRIMES.get(p, "UNKNOWN")
print(f"[*] Identified curve: {curve_name}")


# ---------- Step 2: Classify each signature ----------

def ecdsa_verify(msg, r, s):
    h = int.from_bytes(sha256_str(msg), 'big') % order
    si = modinv(s, order)
    u = (si * h) % order
    v = (si * r) % order
    W = ec_add(ec_mul(u, G, a_coeff, p), ec_mul(v, Q, a_coeff, p), a_coeff, p)
    if W is None:
        return False
    return W[0] % order == r


def ecrdsa_verify(msg, r, s, iso):
    hb = sha256_str(msg)
    h_int = int.from_bytes(hb, 'big') if iso else int.from_bytes(hb[::-1], 'big')
    e = h_int % order
    if e == 0:
        e = 1
    ei = modinv(e, order)
    u = (ei * s) % order
    v = (-ei * r) % order
    W = ec_add(ec_mul(u, G, a_coeff, p), ec_mul(v, Q, a_coeff, p), a_coeff, p)
    if W is None:
        return False
    return W[0] % order == r


sigs = cap["signatures"]
classifications = []

for i, sig in enumerate(sigs):
    msg = sig["message"]
    r_val = int(sig["r"], 16)
    s_val = int(sig["s"], 16)

    if ecdsa_verify(msg, r_val, s_val):
        classifications.append("ecdsa")
    elif ecrdsa_verify(msg, r_val, s_val, False):
        classifications.append("ecrdsa_rfc")
    elif ecrdsa_verify(msg, r_val, s_val, True):
        classifications.append("ecrdsa_iso")
    else:
        classifications.append("unknown")
        print(f"[!] WARNING: sig {i} could not be classified")

    print(f"[*] sig {i}: {classifications[-1]}")


# ---------- Step 3: Find nonce reuse (matching r values) ----------

r_map = {}
reuse_pair = None
for i, sig in enumerate(sigs):
    r_val = sig["r"]
    if r_val in r_map:
        reuse_pair = (r_map[r_val], i)
        break
    r_map[r_val] = i

if reuse_pair is None:
    print("[!] ERROR: No nonce reuse detected")
    sys.exit(1)

idx_a, idx_b = reuse_pair
algo_a = classifications[idx_a]
algo_b = classifications[idx_b]
print(f"[*] Nonce reuse detected: sigs {idx_a} ({algo_a}) and {idx_b} ({algo_b})")


# ---------- Step 4: Cross-algorithm nonce recovery ----------
# The key insight: sig idx_a is ECDSA and sig idx_b is ECRDSA-RFC.
# Standard same-algorithm formulas don't work here.
#
# ECDSA:   s_a = k^-1 * (h_a + d*r)  =>  s_a * k = h_a + d*r
# ECRDSA:  s_b = r*d + k*e_b
#
# From ECDSA:  d = (s_a*k - h_a) / r
# From ECRDSA: d = (s_b - k*e_b) / r
#
# Setting equal: s_a*k - h_a = s_b - k*e_b
#                k*(s_a + e_b) = s_b + h_a
#                k = (s_b + h_a) / (s_a + e_b) mod order

r_shared = int(sigs[idx_a]["r"], 16)
s_a = int(sigs[idx_a]["s"], 16)
s_b = int(sigs[idx_b]["s"], 16)
msg_a = sigs[idx_a]["message"]
msg_b = sigs[idx_b]["message"]

if algo_a == "ecdsa" and algo_b in ("ecrdsa_rfc", "ecrdsa_iso"):
    # idx_a is ECDSA, idx_b is ECRDSA
    iso = (algo_b == "ecrdsa_iso")
    h_ecdsa = int.from_bytes(sha256_str(msg_a), 'big') % order
    hb_ecrdsa = sha256_str(msg_b)
    if iso:
        e_ecrdsa = int.from_bytes(hb_ecrdsa, 'big') % order
    else:
        e_ecrdsa = int.from_bytes(hb_ecrdsa[::-1], 'big') % order
    if e_ecrdsa == 0:
        e_ecrdsa = 1

    # Cross-algorithm formula: k = (s_ecrdsa + h_ecdsa) / (s_ecdsa + e_ecrdsa)
    k_recovered = ((s_b + h_ecdsa) * modinv((s_a + e_ecrdsa) % order, order)) % order
    # d from ECDSA: d = (s_a * k - h_ecdsa) / r
    d_recovered = ((s_a * k_recovered - h_ecdsa) * modinv(r_shared, order)) % order

elif algo_b == "ecdsa" and algo_a in ("ecrdsa_rfc", "ecrdsa_iso"):
    # Reversed: idx_b is ECDSA, idx_a is ECRDSA
    iso = (algo_a == "ecrdsa_iso")
    h_ecdsa = int.from_bytes(sha256_str(msg_b), 'big') % order
    hb_ecrdsa = sha256_str(msg_a)
    if iso:
        e_ecrdsa = int.from_bytes(hb_ecrdsa, 'big') % order
    else:
        e_ecrdsa = int.from_bytes(hb_ecrdsa[::-1], 'big') % order
    if e_ecrdsa == 0:
        e_ecrdsa = 1

    # k = (s_ecrdsa + h_ecdsa) / (s_ecdsa + e_ecrdsa)
    k_recovered = ((s_a + h_ecdsa) * modinv((s_b + e_ecrdsa) % order, order)) % order
    d_recovered = ((s_b * k_recovered - h_ecdsa) * modinv(r_shared, order)) % order

else:
    print(f"[!] ERROR: Unexpected algorithm pair: {algo_a}, {algo_b}")
    sys.exit(1)

# Verify recovery
Q_check = ec_mul(d_recovered, G, a_coeff, p)
assert Q_check == Q, "Key recovery verification failed: d*G != Q"
print(f"[*] Recovered private key: {hex(d_recovered)}")


# ---------- Step 5: Forge ECRDSA-RFC signature ----------

k_forge = int.from_bytes(
    hashlib.sha256(b"deterministic_forge_nonce").digest(), 'big'
) % order

hb_forge = sha256_str(challenge_msg)
h_rfc = int.from_bytes(hb_forge[::-1], 'big')
e_forge = h_rfc % order
if e_forge == 0:
    e_forge = 1

W_forge = ec_mul(k_forge, G, a_coeff, p)
r_forge = W_forge[0] % order
s_forge = (r_forge * d_recovered + k_forge * e_forge) % order
print(f"[*] Forged signature: r={hex(r_forge)[:24]}..., s={hex(s_forge)[:24]}...")


# ---------- Step 6: Compute internal params using libecc_params.py ----------

print("[*] Using /challenge/libecc_params.py to compute internal parameters...")

# Use the provided libecc_params.py tool for both 64-bit and 32-bit
result_64 = subprocess.run(
    ["python3", "/challenge/libecc_params.py", hex(p), "--word-size=64", "--json"],
    capture_output=True, text=True
)
params_64_raw = json.loads(result_64.stdout)["64bit"]

result_32 = subprocess.run(
    ["python3", "/challenge/libecc_params.py", hex(p), "--word-size=32", "--json"],
    capture_output=True, text=True
)
params_32_raw = json.loads(result_32.stdout)["32bit"]

internal_params_64 = {
    "r": params_64_raw["r"],
    "r_squared": params_64_raw["r_squared"],
    "mpinv": params_64_raw["mpinv"],
    "p_reciprocal": params_64_raw["p_reciprocal"],
}

internal_params_32 = {
    "r": params_32_raw["r"],
    "r_squared": params_32_raw["r_squared"],
    "mpinv": params_32_raw["mpinv"],
    "p_reciprocal": params_32_raw["p_reciprocal"],
}

print(f"[*] 64-bit mpinv = {internal_params_64['mpinv']}")
print(f"[*] 32-bit mpinv = {internal_params_32['mpinv']}")


# ---------- Step 7: Write output ----------

output = {
    "curve_name": curve_name,
    "classifications": classifications,
    "vulnerability_type": "cross-algorithm nonce reuse between ECDSA and ECRDSA-RFC signatures",
    "nonce_reuse_pair": [idx_a, idx_b],
    "recovered_private_key": hex(d_recovered),
    "forged_signature": {
        "r": hex(r_forge),
        "s": hex(s_forge)
    },
    "internal_params_64bit": internal_params_64,
    "internal_params_32bit": internal_params_32,
}

with open("/app/output.json", "w") as f:
    json.dump(output, f, indent=2)

print("[*] Solution written to /app/output.json")
