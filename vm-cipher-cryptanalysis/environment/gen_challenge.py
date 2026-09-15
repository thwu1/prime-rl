#!/usr/bin/env python3
"""Generate challenge encrypted sessions at Docker build time.
Must match cipher_engine.c exactly for cross-compatibility."""

import json
import os
import subprocess
import sys

# ---- Constants matching cipher_engine.c ----
PRNG_XOR_INIT = 0xA3B1C6D9
LCG_MUL = 0x41C64E6D
LCG_ADD = 0x3039
FEISTEL_PHI = 0x9E3779B9
DERIVED_KEY_XOR = 0xB16B00B5

# ---- Session parameters ----
ALPHA_SEED = 1718000442
GAMMA_SEED = ALPHA_SEED ^ DERIVED_KEY_XOR
BETA_SEED = 0xDEADBEEF

ALPHA_PLAIN = b"CLASSIFIED//ALPHA\nFLAG_PART_A:OOO{f31st3l_pr\n"
GAMMA_PLAIN = b"CLASSIFIED//GAMMA\nFLAG_PART_B:ng_w34k_s33d}\n"
BETA_PLAIN = b"ROUTINE//BETA\nNO_FLAG_DATA:standard_traffic_only\n"

# ---- PRNG (matches C exactly) ----
def prng_init(seed):
    return (seed ^ PRNG_XOR_INIT) & 0xFFFFFFFF

def prng_step(state):
    return (state * LCG_MUL + LCG_ADD) & 0xFFFFFFFF

def derive_key(seed):
    s = prng_init(seed)
    key = []
    for _ in range(16):
        s = prng_step(s)
        key.append((s >> 16) & 0xFF)
    return bytes(key)

# ---- Feistel cipher (matches C exactly) ----
def ru32(d, o):
    return (d[o] << 24) | (d[o+1] << 16) | (d[o+2] << 8) | d[o+3]

def wu32(v):
    v &= 0xFFFFFFFF
    return bytes([(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])

def feistel_f(x, k):
    x = ((x >> 5) | (x << 27)) & 0xFFFFFFFF
    x ^= k
    x = (x * FEISTEL_PHI) & 0xFFFFFFFF
    x ^= (x >> 16)
    return x & 0xFFFFFFFF

def make_subkey(key, r):
    return ((key[r & 0xF] << 24) | (key[(r*3+1) & 0xF] << 16) |
            (key[(r*5+2) & 0xF] << 8) | key[(r*7+3) & 0xF])

def encrypt_block(blk, key):
    L, R = ru32(blk, 0), ru32(blk, 4)
    for i in range(16):
        t = (L ^ feistel_f(R, make_subkey(key, i))) & 0xFFFFFFFF
        L, R = R, t
    return wu32(L) + wu32(R)

def decrypt_block(blk, key):
    L, R = ru32(blk, 0), ru32(blk, 4)
    for i in range(15, -1, -1):
        t = (R ^ feistel_f(L, make_subkey(key, i))) & 0xFFFFFFFF
        R, L = L, t
    return wu32(L) + wu32(R)

def encrypt_data(pt, key):
    pad = 8 - (len(pt) % 8)
    pt = pt + bytes([pad] * pad)
    out = bytearray()
    for i in range(0, len(pt), 8):
        out.extend(encrypt_block(pt[i:i+8], key))
    return bytes(out)

def decrypt_data(ct, key):
    out = bytearray()
    for i in range(0, len(ct), 8):
        out.extend(decrypt_block(ct[i:i+8], key))
    pad = out[-1]
    if 1 <= pad <= 8 and all(b == pad for b in out[-pad:]):
        out = out[:-pad]
    return bytes(out)

# ---- Self-test ----
print("Running self-tests...", flush=True)
test_key = derive_key(42)
test_ct = encrypt_data(b"TESTTEST", test_key)
test_dec = decrypt_data(test_ct, test_key)
assert test_dec == b"TESTTEST", f"Self-test roundtrip failed: {test_dec}"
print("  Self-test PASSED", flush=True)

# ---- Cross-verify with C binary ----
print("Cross-verifying with C binary...", flush=True)

verify_data = b"CROSSCHK"
with open('/tmp/verify.bin', 'wb') as f:
    f.write(verify_data)

# Verify standard mode encryption
subprocess.run(['/app/cipher_engine', 'e', '42', '/tmp/verify.bin', '/tmp/verify_c.enc'], check=True)
with open('/tmp/verify_c.enc', 'rb') as f:
    c_enc = f.read()
py_enc = encrypt_data(verify_data, derive_key(42))
assert c_enc == py_enc, f"Python/C encrypt mismatch: py={py_enc.hex()} c={c_enc.hex()}"
print("  Standard encrypt MATCHED", flush=True)

# Verify standard mode decryption
subprocess.run(['/app/cipher_engine', 'd', '42', '/tmp/verify_c.enc', '/tmp/verify_dec.bin'], check=True)
with open('/tmp/verify_dec.bin', 'rb') as f:
    c_dec = f.read()
assert c_dec == verify_data, f"C decrypt mismatch: expected={verify_data.hex()} got={c_dec.hex()}"
print("  Standard decrypt MATCHED", flush=True)

# Verify derived key mode (-D flag)
subprocess.run(['/app/cipher_engine', 'e', '-D', '42', '/tmp/verify.bin', '/tmp/verify_d.enc'], check=True)
with open('/tmp/verify_d.enc', 'rb') as f:
    c_derived = f.read()
py_derived = encrypt_data(verify_data, derive_key(42 ^ DERIVED_KEY_XOR))
assert c_derived == py_derived, f"Derived mode mismatch: py={py_derived.hex()} c={c_derived.hex()}"
print("  Derived key mode MATCHED", flush=True)

# Cleanup verification files
for f in ['/tmp/verify.bin', '/tmp/verify_c.enc', '/tmp/verify_dec.bin', '/tmp/verify_d.enc']:
    if os.path.exists(f):
        os.remove(f)

print("Cross-verification PASSED", flush=True)

# ---- Generate encrypted session files ----
print("Generating challenge data...", flush=True)

os.makedirs('/app/encrypted', exist_ok=True)

alpha_enc = encrypt_data(ALPHA_PLAIN, derive_key(ALPHA_SEED))
beta_enc = encrypt_data(BETA_PLAIN, derive_key(BETA_SEED))
gamma_enc = encrypt_data(GAMMA_PLAIN, derive_key(GAMMA_SEED))

with open('/app/encrypted/alpha.enc', 'wb') as f:
    f.write(alpha_enc)
with open('/app/encrypted/beta.enc', 'wb') as f:
    f.write(beta_enc)
with open('/app/encrypted/gamma.enc', 'wb') as f:
    f.write(gamma_enc)

# ---- Write manifest (NO explicit key_mode labels -- solver must infer) ----
manifest = {
    "sessions": {
        "alpha": {
            "file": "alpha.enc",
            "timestamp_start": 1718000400,
            "timestamp_end": 1718000500,
            "operator": "SYS-AUTO",
            "notes": "Primary classified capture. Initiated by automated system scheduler."
        },
        "beta": {
            "file": "beta.enc",
            "timestamp_start": 1718100000,
            "timestamp_end": 1718100100,
            "operator": "HSM-MODULE",
            "notes": "Routine session. Key material provisioned by external hardware security module."
        },
        "gamma": {
            "file": "gamma.enc",
            "timestamp_start": 1718000400,
            "timestamp_end": 1718000500,
            "operator": "SYS-AUTO",
            "notes": "Secondary capture. Same operator session window as alpha. Uses alternate binary invocation."
        }
    },
    "cipher_info": "Custom 16-round Feistel block cipher, 128-bit key, ECB mode, PKCS7 padding.",
    "binary_usage": "cipher_engine <e|d> [options] <seed> <input> [output]"
}

with open('/app/encrypted/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

# ---- Write audit notes (intentionally sparse -- raw findings only) ----
audit_notes = """PRELIMINARY BINARY SURVEY
=========================
Analyst: [REDACTED]
Date: 2024-06-10
Status: INCOMPLETE - transferred to your team for full analysis

Observations:
- Target: ELF64, x86-64, dynamically linked, fully stripped (no symbols)
- At least two distinct key derivation code paths identified via control flow analysis
- One code path is conditional on a string comparison of a command-line argument
- Multiple large 32-bit constants embedded in .text section
- Arithmetic patterns consistent with PRNG usage (multiply-accumulate sequences)
- Block-oriented processing loop with fixed iteration count observed
- PKCS-style padding logic present in output path

No further analysis performed. Full reverse engineering required to assess
per-session vulnerability and determine recoverability.
"""

with open('/app/audit_notes.txt', 'w') as f:
    f.write(audit_notes)

print("Challenge data generated successfully.", flush=True)
