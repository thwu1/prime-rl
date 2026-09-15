"""
Generate /app/verification_results.json by running the exhaustive verifier
on all six transfer functions.
"""

import sys
sys.path.insert(0, "/app")

import json
from transfer_functions import (
    transfer_add, transfer_sub, transfer_mul,
    transfer_shl, transfer_lshr, transfer_udiv,
)
from verifier import verify_soundness_binary, measure_precision_binary

W = 4


def c_add(x, y):
    return x + y

def c_sub(x, y):
    return x - y

def c_mul(x, y):
    return x * y

def c_shl(x, y):
    return 0 if y >= 64 else (x << y)

def c_lshr(x, y):
    return 0 if y >= 64 else (x >> y)

def c_udiv(x, y):
    return 0 if y == 0 else x // y


ops = {
    "add": (transfer_add, c_add),
    "sub": (transfer_sub, c_sub),
    "mul": (transfer_mul, c_mul),
    "shl": (transfer_shl, c_shl),
    "lshr": (transfer_lshr, c_lshr),
    "udiv": (transfer_udiv, c_udiv),
}

results = {}
for name, (tfn, cfn) in ops.items():
    ok, _ = verify_soundness_binary(tfn, cfn, W)
    p = measure_precision_binary(tfn, cfn, W)
    results[name] = {"sound": ok, "precision": round(p, 6)}

with open("/app/verification_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Verification report written to /app/verification_results.json")
for name, r in results.items():
    print(f"  {name}: sound={r['sound']}  precision={r['precision']:.4f}")
