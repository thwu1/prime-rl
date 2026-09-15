#!/usr/bin/env python3

"""
Fixed PQC Python verification.

Fixes vs. the buggy /app/pqc-migration/verify_migration.py:
  1. Uses get_enabled_kem_mechanisms() / get_enabled_sig_mechanisms()
     instead of hardcoded legacy names (Kyber/Dilithium).
  2. Properly iterates only enabled algorithms.
"""

import json
import os
import oqs

os.makedirs("/app/output", exist_ok=True)

audit = []

# ── KEM algorithms ──
for alg_name in oqs.get_enabled_kem_mechanisms():
    with oqs.KeyEncapsulation(alg_name) as receiver:
        d = receiver.details
        audit.append({
            "name": alg_name,
            "type": "KEM",
            "nist_level": d["claimed_nist_level"],
            "public_key_length": d["length_public_key"],
            "secret_key_length": d["length_secret_key"],
            "ciphertext_length": d["length_ciphertext"],
            "shared_secret_length": d["length_shared_secret"],
        })

# ── SIG algorithms ──
for alg_name in oqs.get_enabled_sig_mechanisms():
    with oqs.Signature(alg_name) as signer:
        d = signer.details
        audit.append({
            "name": alg_name,
            "type": "SIG",
            "nist_level": d["claimed_nist_level"],
            "public_key_length": d["length_public_key"],
            "secret_key_length": d["length_secret_key"],
            "signature_length": d["length_signature"],
        })

with open("/app/output/py_audit.json", "w") as f:
    json.dump(audit, f, indent=2)

kems = [a for a in audit if a["type"] == "KEM"]
sigs = [a for a in audit if a["type"] == "SIG"]
print(f"Python audit: {len(kems)} KEM + {len(sigs)} SIG algorithms.")
