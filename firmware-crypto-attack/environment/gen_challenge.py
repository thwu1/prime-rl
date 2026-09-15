#!/usr/bin/env python3
"""
Generate the TUF rollback forgery challenge.

Creates a TUF repository with three RSA signing keys:
  - Strong 2048-bit key (root role) -- cannot be factored
  - Weak 1024-bit key with close primes (targets role) -- Fermat-factorable
  - Weak 1024-bit key sharing a prime with the targets key (snapshot+timestamp) -- GCD-attackable

An old target file containing a debug flag was removed from TUF tracking (v2)
but the file still exists in the targets/ directory. The solver must crack the
weak keys, forge TUF metadata to re-add the old file, and extract the flag.
"""

import json
import hashlib
import os
import secrets
import shutil
import random
import textwrap
import math
from sympy import nextprime

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateNumbers, RSAPublicNumbers,
    rsa_crt_iqmp, rsa_crt_dmp1, rsa_crt_dmq1
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend

# ======================== Constants ========================

E = 65537
SEED = 0xC0FFEE_DEAD_BEEF

# Generate a unique flag per build using cryptographic randomness (DNA)
DNA_TOKEN = secrets.token_hex(16)
FLAG = f"FLAG{{tuf_rollback_forge_{DNA_TOKEN}}}"

rng = random.Random(SEED)


# ======================== Helpers ========================

def canonical_json(obj):
    """TUF-compatible canonical JSON encoding."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


def compute_keyid(key_dict):
    """TUF key ID = SHA-256 of canonical JSON of key dict."""
    return hashlib.sha256(canonical_json(key_dict)).hexdigest()


def file_hashes(data):
    """Compute SHA-256 and SHA-512 hashes of raw bytes."""
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha512": hashlib.sha512(data).hexdigest(),
    }


def key_to_pem_public(pub_key):
    return pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def make_rsa_from_primes(p, q, e=E):
    """Build an RSA private key object from known primes."""
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


def tuf_key_dict(pub_key):
    """Create TUF key metadata dictionary for a public key."""
    return {
        "keytype": "rsa",
        "scheme": "rsassa-pss-sha256",
        "keyid_hash_algorithms": ["sha256", "sha512"],
        "keyval": {"public": key_to_pem_public(pub_key)},
    }


def sign_metadata(signed_dict, priv_key, keyid):
    """Sign TUF metadata: canonical-JSON of 'signed', RSA-PSS-SHA256."""
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


# ======================== Key Generation ========================

# 1) Strong root key -- 2048-bit, well-separated primes (unfactorable)
p_strong_base = rng.getrandbits(1024) | (1 << 1023) | 1
p_strong = int(nextprime(p_strong_base))
q_strong_base = rng.getrandbits(1024) | (1 << 1023) | 1
q_strong = int(nextprime(q_strong_base))
strong_key = make_rsa_from_primes(p_strong, q_strong)

# 2) Fermat-factorable targets key -- 1024-bit, close primes
p_base = rng.getrandbits(512) | (1 << 511) | 1
p_fermat = int(nextprime(p_base))
# q is close to p: differ by ~2^22  (Fermat converges in 1-2 steps)
delta = rng.randint(2 ** 20, 2 ** 23)
q_fermat = int(nextprime(p_fermat + delta))
fermat_key = make_rsa_from_primes(p_fermat, q_fermat)

# 3) GCD-attackable snapshot/timestamp key -- shares p_fermat with key 2
s_base = rng.getrandbits(512) | (1 << 511) | 1
s_gcd = int(nextprime(s_base))
gcd_key = make_rsa_from_primes(p_fermat, s_gcd)

# ======================== Key Metadata ========================

strong_kd = tuf_key_dict(strong_key.public_key())
fermat_kd = tuf_key_dict(fermat_key.public_key())
gcd_kd = tuf_key_dict(gcd_key.public_key())

strong_kid = compute_keyid(strong_kd)
fermat_kid = compute_keyid(fermat_kd)
gcd_kid = compute_keyid(gcd_kd)

# ======================== Target Files ========================

fw_v010 = (
    '#!/usr/bin/env python3\n'
    '"""Firmware v0.1.0 - Debug build"""\n'
    'import sys\n'
    'print("Firmware v0.1.0 loaded")\n'
    f'print("Debug token: {FLAG}")\n'
    'print("WARNING: Debug build - not for production")\n'
    'sys.exit(0)\n'
).encode()

fw_v020 = (
    '#!/usr/bin/env python3\n'
    '"""Firmware v0.2.0 - Stable release"""\n'
    'import sys\n'
    'print("Firmware v0.2.0 loaded")\n'
    'print("Production build - debug tokens removed")\n'
    'sys.exit(0)\n'
).encode()

fw_v030 = (
    '#!/usr/bin/env python3\n'
    '"""Firmware v0.3.0 - Latest release"""\n'
    'import sys\n'
    'print("Firmware v0.3.0 loaded")\n'
    'print("Production build - security patches applied")\n'
    'sys.exit(0)\n'
).encode()

targets = {
    "firmware_v0.1.0.py": fw_v010,
    "firmware_v0.2.0.py": fw_v020,
    "firmware_v0.3.0.py": fw_v030,
}

# ======================== TUF Metadata ========================

EXPIRES = "2030-01-01T00:00:00Z"

# ---- root.json (v1) ----
root_signed = {
    "_type": "root",
    "spec_version": "1.0.31",
    "version": 1,
    "expires": EXPIRES,
    "consistent_snapshot": True,
    "keys": {
        strong_kid: strong_kd,
        fermat_kid: fermat_kd,
        gcd_kid: gcd_kd,
    },
    "roles": {
        "root": {"keyids": [strong_kid], "threshold": 1},
        "targets": {"keyids": [fermat_kid], "threshold": 1},
        "snapshot": {"keyids": [gcd_kid], "threshold": 1},
        "timestamp": {"keyids": [gcd_kid], "threshold": 1},
    },
}
root_md = sign_metadata(root_signed, strong_key, strong_kid)

# ---- targets.json v1 (old -- includes v0.1.0) ----
targets_v1_signed = {
    "_type": "targets",
    "spec_version": "1.0.31",
    "version": 1,
    "expires": EXPIRES,
    "targets": {
        "firmware_v0.1.0.py": {
            "length": len(fw_v010),
            "hashes": file_hashes(fw_v010),
        },
        "firmware_v0.2.0.py": {
            "length": len(fw_v020),
            "hashes": file_hashes(fw_v020),
        },
    },
}
targets_v1_md = sign_metadata(targets_v1_signed, fermat_key, fermat_kid)

# ---- targets.json v2 (current -- v0.1.0 REMOVED) ----
targets_v2_signed = {
    "_type": "targets",
    "spec_version": "1.0.31",
    "version": 2,
    "expires": EXPIRES,
    "targets": {
        "firmware_v0.2.0.py": {
            "length": len(fw_v020),
            "hashes": file_hashes(fw_v020),
        },
        "firmware_v0.3.0.py": {
            "length": len(fw_v030),
            "hashes": file_hashes(fw_v030),
        },
    },
}
targets_v2_md = sign_metadata(targets_v2_signed, fermat_key, fermat_kid)

# ---- snapshot.json v1 ----
snapshot_v1_signed = {
    "_type": "snapshot",
    "spec_version": "1.0.31",
    "version": 1,
    "expires": EXPIRES,
    "meta": {
        "targets.json": {"version": 1},
    },
}
snapshot_v1_md = sign_metadata(snapshot_v1_signed, gcd_key, gcd_kid)

# ---- snapshot.json v2 (current) ----
snapshot_v2_signed = {
    "_type": "snapshot",
    "spec_version": "1.0.31",
    "version": 2,
    "expires": EXPIRES,
    "meta": {
        "targets.json": {"version": 2},
    },
}
snapshot_v2_md = sign_metadata(snapshot_v2_signed, gcd_key, gcd_kid)

# ---- timestamp.json (current, version 2) ----
snap_v2_bytes = json.dumps(snapshot_v2_md, indent=2).encode()
timestamp_signed = {
    "_type": "timestamp",
    "spec_version": "1.0.31",
    "version": 2,
    "expires": EXPIRES,
    "meta": {
        "snapshot.json": {
            "version": 2,
            "length": len(snap_v2_bytes),
            "hashes": {"sha256": hashlib.sha256(snap_v2_bytes).hexdigest()},
        },
    },
}
timestamp_md = sign_metadata(timestamp_signed, gcd_key, gcd_kid)

# ======================== Write Repository ========================

repo = "/app/repository"
tgt_dir = os.path.join(repo, "targets")
os.makedirs(tgt_dir, exist_ok=True)

# Metadata files
write_json(os.path.join(repo, "root.json"), root_md)
write_json(os.path.join(repo, "1.root.json"), root_md)

write_json(os.path.join(repo, "1.targets.json"), targets_v1_md)
write_json(os.path.join(repo, "2.targets.json"), targets_v2_md)
write_json(os.path.join(repo, "targets.json"), targets_v2_md)

write_json(os.path.join(repo, "1.snapshot.json"), snapshot_v1_md)
write_json(os.path.join(repo, "2.snapshot.json"), snapshot_v2_md)
write_json(os.path.join(repo, "snapshot.json"), snapshot_v2_md)

write_json(os.path.join(repo, "timestamp.json"), timestamp_md)

# Target files (hash-prefixed for consistent_snapshot)
for name, data in targets.items():
    h = file_hashes(data)["sha256"]
    with open(os.path.join(tgt_dir, f"{h}.{name}"), "wb") as f:
        f.write(data)

# Metadata symlink (TUF convention)
os.symlink(".", os.path.join(repo, "metadata"))

# README
readme = textwrap.dedent("""\
    Automotive Firmware TUF Repository
    ===================================

    This repository uses The Update Framework (TUF) to securely distribute
    firmware updates for an automotive telematics control module (TCM).

    An internal security audit discovered that firmware_v0.1.0.py (a debug build)
    was accidentally published with an embedded debug token. The file was removed
    from TUF tracking in targets.json v2, but the physical file was NOT deleted
    from the targets/ directory due to a retention policy.

    Your objective is to forge valid TUF metadata that re-adds the old
    firmware_v0.1.0.py as a tracked target, enabling it to pass TUF client
    verification. Extract the debug token from the recovered file.

    Repository layout:
      root.json            Root of trust (defines signing keys and role assignments)
      1.targets.json       Old targets metadata (v1) -- included v0.1.0
      targets.json         Current targets metadata (v2) -- v0.1.0 removed
      snapshot.json        Current snapshot metadata (v2)
      timestamp.json       Current timestamp metadata (v2)
      targets/             Hash-prefixed target files (consistent snapshots)

    The root.json assigns THREE separate RSA keys to four TUF roles.
    Examine the key assignments and key properties carefully.
""")

with open(os.path.join(repo, "README.txt"), "w") as f:
    f.write(readme)

# ======================== Write Flag Verification Hash ========================
# Store the SHA-256 hash of the flag for test verification.
# This file is copied to the final Docker image so tests can validate
# without hardcoding the flag hash.
flag_hash = hashlib.sha256(FLAG.encode()).hexdigest()
with open("/app/.flag_verification_hash", "w") as f:
    f.write(flag_hash)

# ======================== Summary ========================

print("TUF rollback forgery challenge generated")
print(f"  Root key ID:                    {strong_kid[:16]}...")
print(f"  Targets key ID (Fermat-weak):   {fermat_kid[:16]}...")
print(f"  Snap/TS key ID (GCD-weak):      {gcd_kid[:16]}...")
print(f"  Flag SHA-256: {flag_hash}")
print(f"  DNA token: {DNA_TOKEN}")

for name, data in targets.items():
    h = file_hashes(data)["sha256"]
    print(f"  {name}: sha256={h[:16]}... len={len(data)}")
