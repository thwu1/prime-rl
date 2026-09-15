#!/usr/bin/env python3
"""Diagnose vulnerabilities in /app/crypto_service.py by running
Wycheproof test vectors and analysing failure patterns."""

import json, sys, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
sys.path.insert(0, "/app")
import crypto_service as cs

def load(name):
    with open(f"/app/vectors/{name}") as f:
        return json.load(f)

bugs_found = []

# ---- AES-GCM: zero-length IV ----
data = load("aes_gcm_test.json")
for grp in data["testGroups"]:
    for t in grp["tests"]:
        if t["result"] == "valid":
            # Encrypt with the MD5-derived fallback nonce
            key = bytes.fromhex(t["key"])
            derived_iv = hashlib.md5(key).digest()[:12]
            pt = b"\x42" * 16
            ct_tag = AESGCM(key).encrypt(derived_iv, pt, b"")
            ct_hex = ct_tag[:-16].hex()
            tag_hex = ct_tag[-16:].hex()
            got = cs.aes_gcm_decrypt(t["key"], "", ct_hex, tag_hex, "")
            if got is not None:
                bugs_found.append("ZeroLengthIv")
                print("[DIAG] BUG: aes_gcm_decrypt accepts zero-length IV")
            break
    break

# ---- ECDSA: InvalidSignature (r=0/s=0) ----
data = load("ecdsa_secp256r1_sha256_test.json")
for grp in data["testGroups"]:
    pk = grp["publicKeyDer"]
    for t in grp["tests"]:
        if "InvalidSignature" in t.get("flags", []):
            ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
            if ok:
                bugs_found.append("InvalidSignature")
                print(f"[DIAG] BUG: ecdsa_verify accepts r=0/s=0 "
                      f"(tcId={t['tcId']})")
            break
    if "InvalidSignature" in bugs_found:
        break

# ---- ECDSA: BER encoding ----
for grp in data["testGroups"]:
    pk = grp["publicKeyDer"]
    for t in grp["tests"]:
        if "BerEncodedSignature" in t.get("flags", []):
            ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
            if ok:
                bugs_found.append("BerEncodedSignature")
                print(f"[DIAG] BUG: ecdsa_verify accepts BER sigs "
                      f"(tcId={t['tcId']})")
            break
    if "BerEncodedSignature" in bugs_found:
        break

# ---- ECDSA: RangeCheck (r%n / s%n) ----
for grp in data["testGroups"]:
    pk = grp["publicKeyDer"]
    for t in grp["tests"]:
        if "RangeCheck" in t.get("flags", []) and t["result"] == "invalid":
            ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
            if ok:
                bugs_found.append("RangeCheck")
                print(f"[DIAG] BUG: ecdsa_verify accepts out-of-range r/s "
                      f"(tcId={t['tcId']})")
            break
    if "RangeCheck" in bugs_found:
        break

# ---- X25519: ZeroSharedSecret ----
data = load("x25519_test.json")
for grp in data["testGroups"]:
    for t in grp["tests"]:
        if "ZeroSharedSecret" in t.get("flags", []):
            got = cs.x25519_exchange(t["private"], t["public"])
            if got is not None and got == "0" * 64:
                bugs_found.append("ZeroSharedSecret")
                print(f"[DIAG] BUG: x25519_exchange returns all-zero "
                      f"(tcId={t['tcId']})")
            break
    break

print(f"\n[DIAG] Total bugs found: {len(bugs_found)}")
for b in bugs_found:
    print(f"  - {b}")
