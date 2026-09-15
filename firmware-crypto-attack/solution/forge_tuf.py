#!/usr/bin/env python3
"""
Solve the TUF rollback forgery challenge.

Strategy:
  1. Parse root.json to extract RSA public keys and role assignments.
  2. For each key, extract the modulus and try Fermat factoring.
  3. Compute pairwise GCDs of all moduli to find shared factors.
  4. Reconstruct private keys from recovered primes.
  5. Read 1.targets.json to get the old firmware_v0.1.0.py entry.
  6. Build forged targets.json v3, snapshot.json v3, timestamp.json v3.
  7. Sign each with the appropriate recovered private key.
  8. Extract the flag from the old firmware file.
"""

import json
import hashlib
import math
import os
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateNumbers,
    RSAPublicNumbers,
    rsa_crt_dmp1,
    rsa_crt_dmq1,
    rsa_crt_iqmp,
)
from cryptography.hazmat.backends import default_backend

REPO_DIR = "/app/repository"
FORGED_DIR = "/app/forged_repository"
E = 65537


# ======================== Helpers ========================


def canonical_json(obj):
    """TUF canonical JSON encoding."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


def fermat_factor(n, max_iter=1_000_000):
    """Fermat factorization: works when p and q are close."""
    a = math.isqrt(n)
    if a * a < n:
        a += 1
    for _ in range(max_iter):
        b2 = a * a - n
        b = math.isqrt(b2)
        if b * b == b2:
            p = a + b
            q = a - b
            if p > 1 and q > 1 and p * q == n:
                return p, q
        a += 1
    return None


def reconstruct_private_key(p, q, e=E):
    """Build RSA private key from primes."""
    n = p * q
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    pub = RSAPublicNumbers(e, n)
    priv = RSAPrivateNumbers(
        p, q, d,
        rsa_crt_dmp1(d, p),
        rsa_crt_dmq1(d, q),
        rsa_crt_iqmp(p, q),
        pub,
    )
    return priv.private_key(default_backend())


def sign_metadata(signed_dict, priv_key, keyid):
    """Sign TUF metadata with RSA-PSS-SHA256."""
    data = canonical_json(signed_dict)
    sig = priv_key.sign(
        data,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "signed": signed_dict,
        "signatures": [{"keyid": keyid, "sig": sig.hex()}],
    }


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


# ======================== Step 1: Parse root.json ========================

print("[*] Loading root.json...")
with open(os.path.join(REPO_DIR, "root.json")) as f:
    root = json.load(f)

roles = root["signed"]["roles"]
keys = root["signed"]["keys"]

# Map role -> (keyid, public_key_pem, public_key_obj)
role_keys = {}
for role_name in ["root", "targets", "snapshot", "timestamp"]:
    kid = roles[role_name]["keyids"][0]
    pem = keys[kid]["keyval"]["public"].encode()
    pub = serialization.load_pem_public_key(pem, backend=default_backend())
    role_keys[role_name] = {"keyid": kid, "public_key": pub}
    n = pub.public_numbers().n
    print(f"  {role_name}: keyid={kid[:16]}... modulus_bits={n.bit_length()}")

# Collect unique key IDs and their moduli
unique_keys = {}
for role_name, info in role_keys.items():
    kid = info["keyid"]
    if kid not in unique_keys:
        n = info["public_key"].public_numbers().n
        unique_keys[kid] = {"modulus": n, "roles": [role_name]}
    else:
        unique_keys[kid]["roles"].append(role_name)

print(f"[*] Found {len(unique_keys)} unique keys")
for kid, info in unique_keys.items():
    print(f"  {kid[:16]}... -> roles: {info['roles']}")

# ======================== Step 2: Factor weak keys ========================

print("\n[*] Attempting Fermat factoring on each key...")
factored = {}
for kid, info in unique_keys.items():
    n = info["modulus"]
    result = fermat_factor(n, max_iter=100_000)
    if result:
        p, q = result
        print(f"  [+] Key {kid[:16]}... FACTORED via Fermat! (roles: {info['roles']})")
        factored[kid] = (p, q)
    else:
        print(f"  [-] Key {kid[:16]}... not Fermat-factorable (roles: {info['roles']})")

print("\n[*] Attempting pairwise GCD on all key moduli...")
kids = list(unique_keys.keys())
for i in range(len(kids)):
    for j in range(i + 1, len(kids)):
        n_i = unique_keys[kids[i]]["modulus"]
        n_j = unique_keys[kids[j]]["modulus"]
        g = math.gcd(n_i, n_j)
        if g > 1:
            print(f"  [+] GCD({kids[i][:16]}..., {kids[j][:16]}...) = shared factor!")
            # Factor both keys using the shared factor
            if kids[i] not in factored:
                p = g
                q = n_i // p
                assert p * q == n_i
                factored[kids[i]] = (p, q)
                print(f"      Factored key {kids[i][:16]}... via GCD")
            if kids[j] not in factored:
                p = g
                q = n_j // p
                assert p * q == n_j
                factored[kids[j]] = (p, q)
                print(f"      Factored key {kids[j][:16]}... via GCD")

# ======================== Step 3: Reconstruct private keys ========================

print("\n[*] Reconstructing private keys...")
private_keys = {}
for kid, (p, q) in factored.items():
    priv = reconstruct_private_key(p, q)
    private_keys[kid] = priv
    roles_str = ", ".join(unique_keys[kid]["roles"])
    print(f"  Recovered private key for: {roles_str}")

# Verify we have keys for targets, snapshot, timestamp
targets_kid = role_keys["targets"]["keyid"]
snapshot_kid = role_keys["snapshot"]["keyid"]
timestamp_kid = role_keys["timestamp"]["keyid"]

assert targets_kid in private_keys, "Failed to recover targets signing key!"
assert snapshot_kid in private_keys, "Failed to recover snapshot signing key!"
assert timestamp_kid in private_keys, "Failed to recover timestamp signing key!"

print("[+] All required private keys recovered!")

# ======================== Step 4: Read old targets entry ========================

print("\n[*] Reading old targets metadata...")
with open(os.path.join(REPO_DIR, "1.targets.json")) as f:
    old_targets = json.load(f)

old_fw_entry = old_targets["signed"]["targets"]["firmware_v0.1.0.py"]
print(f"  firmware_v0.1.0.py: length={old_fw_entry['length']}")
print(f"  sha256={old_fw_entry['hashes']['sha256'][:32]}...")

# ======================== Step 5: Forge TUF metadata ========================

print("\n[*] Forging TUF metadata...")
os.makedirs(FORGED_DIR, exist_ok=True)

EXPIRES = "2030-01-01T00:00:00Z"

# Read current targets to include existing files too
with open(os.path.join(REPO_DIR, "targets.json")) as f:
    current_targets = json.load(f)

# targets.json v3 - re-adds firmware_v0.1.0.py
forged_targets_signed = {
    "_type": "targets",
    "spec_version": "1.0.31",
    "version": 3,
    "expires": EXPIRES,
    "targets": {
        "firmware_v0.1.0.py": old_fw_entry,
        **current_targets["signed"]["targets"],
    },
}
forged_targets = sign_metadata(forged_targets_signed, private_keys[targets_kid], targets_kid)
write_json(os.path.join(FORGED_DIR, "targets.json"), forged_targets)
print("  [+] Wrote forged targets.json v3")

# snapshot.json v3
forged_snapshot_signed = {
    "_type": "snapshot",
    "spec_version": "1.0.31",
    "version": 3,
    "expires": EXPIRES,
    "meta": {
        "targets.json": {"version": 3},
    },
}
forged_snapshot = sign_metadata(forged_snapshot_signed, private_keys[snapshot_kid], snapshot_kid)
write_json(os.path.join(FORGED_DIR, "snapshot.json"), forged_snapshot)
print("  [+] Wrote forged snapshot.json v3")

# timestamp.json v3
snap_bytes = json.dumps(forged_snapshot, indent=2).encode()
forged_timestamp_signed = {
    "_type": "timestamp",
    "spec_version": "1.0.31",
    "version": 3,
    "expires": EXPIRES,
    "meta": {
        "snapshot.json": {
            "version": 3,
            "length": len(snap_bytes),
            "hashes": {"sha256": hashlib.sha256(snap_bytes).hexdigest()},
        },
    },
}
forged_timestamp = sign_metadata(forged_timestamp_signed, private_keys[timestamp_kid], timestamp_kid)
write_json(os.path.join(FORGED_DIR, "timestamp.json"), forged_timestamp)
print("  [+] Wrote forged timestamp.json v3")

# ======================== Step 6: Extract flag ========================

print("\n[*] Extracting flag from old firmware file...")
fw_hash = old_fw_entry["hashes"]["sha256"]
fw_path = os.path.join(REPO_DIR, "targets", f"{fw_hash}.firmware_v0.1.0.py")

with open(fw_path, "r") as f:
    content = f.read()

match = re.search(r"FLAG\{[^}]+\}", content)
if match:
    flag = match.group(0)
    with open("/app/flag.txt", "w") as f:
        f.write(flag)
    print(f"[+] Flag: {flag}")
else:
    print("[-] Flag not found in firmware file!")
    raise SystemExit(1)

print("\n[+] Challenge solved!")
