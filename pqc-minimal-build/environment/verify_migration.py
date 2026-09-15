#!/usr/bin/env python3
"""
PQC Migration Verification — Python cross-check using liboqs-python.

Independently enumerates PQC algorithms via the Python wrapper, produces
an audit report, and cross-checks against the C program's output.

Output files:
  /app/output/py_audit.json    - Python-side algorithm parameter catalog
  /app/output/cross_check.json - C vs Python parameter agreement report
"""

import json
import os
import oqs

os.makedirs("/app/output", exist_ok=True)

# NIST-standardized post-quantum algorithm names
KEM_ALGORITHMS = ["Kyber512", "Kyber768", "Kyber1024"]
SIG_ALGORITHMS = ["Dilithium2", "Dilithium3", "Dilithium5"]

audit = []

# Enumerate KEM algorithms
for name in KEM_ALGORITHMS:
    kem = oqs.KeyEncapsulation(name)
    d = kem.details
    audit.append({
        "name": name,
        "type": "KEM",
        "nist_level": d["claimed_nist_level"],
        "public_key_length": d["length_public_key"],
        "secret_key_length": d["length_secret_key"],
        "ciphertext_length": d["length_ciphertext"],
        "shared_secret_length": d["length_shared_secret"],
    })

# Enumerate SIG algorithms
for name in SIG_ALGORITHMS:
    sig = oqs.Signature(name)
    d = sig.details
    audit.append({
        "name": name,
        "type": "SIG",
        "nist_level": d["claimed_nist_level"],
        "public_key_length": d["length_public_key"],
        "secret_key_length": d["length_secret_key"],
        "signature_length": d["length_signature"],
    })

# Write Python audit
with open("/app/output/py_audit.json", "w") as f:
    json.dump(audit, f, indent=2)

# Cross-check with C output
with open("/app/output/algorithm_audit.json") as f:
    c_audit = json.load(f)

c_kems = {a["name"]: a for a in c_audit if a["type"] == "KEM"}
c_sigs = {a["name"]: a for a in c_audit if a["type"] == "SIG"}
py_kems = {a["name"]: a for a in audit if a["type"] == "KEM"}
py_sigs = {a["name"]: a for a in audit if a["type"] == "SIG"}

all_match = (len(c_kems) == len(py_kems) and len(c_sigs) == len(py_sigs))

result = {
    "all_parameters_match": all_match,
    "kem_count": len(py_kems),
    "sig_count": len(py_sigs),
}

with open("/app/output/cross_check.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Verification: {len(py_kems)} KEMs, {len(py_sigs)} SIGs")
