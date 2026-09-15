#!/usr/bin/env python3

"""
Cross-check: compare C and Python audit outputs for parameter agreement.
"""

import json
import os

c_path = "/app/output/algorithm_audit.json"
py_path = "/app/output/py_audit.json"

with open(c_path) as f:
    c_audit = json.load(f)
with open(py_path) as f:
    py_audit = json.load(f)

c_kems = {a["name"]: a for a in c_audit if a["type"] == "KEM"}
c_sigs = {a["name"]: a for a in c_audit if a["type"] == "SIG"}
py_kems = {a["name"]: a for a in py_audit if a["type"] == "KEM"}
py_sigs = {a["name"]: a for a in py_audit if a["type"] == "SIG"}

all_match = True
mismatches = []

# Compare KEM parameters
kem_keys = ["nist_level", "public_key_length", "secret_key_length",
            "ciphertext_length", "shared_secret_length"]
for name in c_kems:
    if name not in py_kems:
        all_match = False
        mismatches.append(f"KEM {name} missing from Python output")
        continue
    for key in kem_keys:
        if c_kems[name].get(key) != py_kems[name].get(key):
            all_match = False
            mismatches.append(
                f"KEM {name}.{key}: C={c_kems[name].get(key)} vs Py={py_kems[name].get(key)}"
            )

# Compare SIG parameters
sig_keys = ["nist_level", "public_key_length", "secret_key_length",
            "signature_length"]
for name in c_sigs:
    if name not in py_sigs:
        all_match = False
        mismatches.append(f"SIG {name} missing from Python output")
        continue
    for key in sig_keys:
        if c_sigs[name].get(key) != py_sigs[name].get(key):
            all_match = False
            mismatches.append(
                f"SIG {name}.{key}: C={c_sigs[name].get(key)} vs Py={py_sigs[name].get(key)}"
            )

result = {
    "all_parameters_match": all_match,
    "kem_count": len(c_kems),
    "sig_count": len(c_sigs),
}
if mismatches:
    result["mismatches"] = mismatches

with open("/app/output/cross_check.json", "w") as f:
    json.dump(result, f, indent=2)

status = "PASS" if all_match else "FAIL"
print(f"Cross-check {status}: {len(c_kems)} KEMs, {len(c_sigs)} SIGs.")
if mismatches:
    for m in mismatches:
        print(f"  MISMATCH: {m}")
