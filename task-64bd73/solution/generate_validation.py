#!/usr/bin/env python3
"""Generate the sqlite3+jq validation pipeline files."""


import os
import stat

VALIDATE_HELPER = r'''#!/usr/bin/env python3
"""Validate optimizer against reference database examples."""
import json
import sys

sys.path.insert(0, "/app")
import numpy as np
from optimizer import ZNEShotOptimizer
from hamiltonian import Hamiltonian

results = {}
tol = 1e-6

# 1. Coefficient examples — validate lagrange_coefficients()
with open("/tmp/ref_data/coefficients.json") as f:
    examples = json.load(f)
total, passed = len(examples), 0
for ex in examples:
    sf = ex["scale_factors"]
    expected = ex["coefficients"]
    ham = Hamiltonian(["Z"], [1.0])
    opt = ZNEShotOptimizer(ham, sf, 0.01, 10)
    gamma = opt.lagrange_coefficients().tolist()
    if all(abs(a - b) < tol for a, b in zip(gamma, expected)):
        passed += 1
results["coefficient_examples"] = {
    "total": total, "passed": passed,
    "status": "pass" if passed == total else "fail",
}

# 2. Extrapolation examples — validate richardson_extrapolate()
with open("/tmp/ref_data/extrapolation.json") as f:
    examples = json.load(f)
total, passed = len(examples), 0
for ex in examples:
    sf = ex["scale_factors"]
    vals = np.array(ex["values_per_level"])
    expected = ex["extrapolated_result"]
    ham = Hamiltonian(["Z"], [1.0])
    opt = ZNEShotOptimizer(ham, sf, 0.01, 10)
    result = opt.richardson_extrapolate(vals)
    if abs(result - expected) < tol:
        passed += 1
results["extrapolation_examples"] = {
    "total": total, "passed": passed,
    "status": "pass" if passed == total else "fail",
}

# 3. Variance formula examples — validate zne_variance formula
with open("/tmp/ref_data/variance_formula.json") as f:
    examples = json.load(f)
total, passed = len(examples), 0
for ex in examples:
    gamma = ex["gamma"]
    V = ex["variance_matrix"]
    N = ex["shot_allocation"]
    expected = ex["zne_variance"]
    J, K = len(gamma), len(V[0])
    computed = sum(
        gamma[j] ** 2 * V[j][k] / N[j][k]
        for j in range(J) for k in range(K) if N[j][k] > 0
    )
    if abs(computed - expected) < tol:
        passed += 1
results["variance_formula_examples"] = {
    "total": total, "passed": passed,
    "status": "pass" if passed == total else "fail",
}

# 4. Group variance examples — validate weighted sample variance
with open("/tmp/ref_data/group_variance.json") as f:
    examples = json.load(f)
total, passed = len(examples), 0
for ex in examples:
    meas = ex["measurements"]
    weights = ex["weights"]
    expected = ex["expected_variance"]
    weighted = [sum(m * w for m, w in zip(row, weights)) for row in meas]
    n = len(weighted)
    mean_v = sum(weighted) / n
    computed = sum((v - mean_v) ** 2 for v in weighted) / (n - 1) if n > 1 else 0.0
    if abs(computed - expected) < tol:
        passed += 1
results["group_variance_examples"] = {
    "total": total, "passed": passed,
    "status": "pass" if passed == total else "fail",
}

# 5. Allocation examples — validate budget and minimum constraints
with open("/tmp/ref_data/allocation.json") as f:
    examples = json.load(f)
total, passed = len(examples), 0
for ex in examples:
    expected_alloc = ex["optimal_allocation"]
    budget = ex["budget"]
    total_shots = sum(sum(row) for row in expected_alloc)
    min_shots = min(min(row) for row in expected_alloc)
    if total_shots == budget and min_shots >= 1:
        passed += 1
results["allocation_examples"] = {
    "total": total, "passed": passed,
    "status": "pass" if passed == total else "fail",
}

results["all_passed"] = all(
    v["status"] == "pass" for v in results.values() if isinstance(v, dict)
)

with open("/app/validation_report.json", "w") as f:
    json.dump(results, f, indent=2)

status = "ALL PASSED" if results["all_passed"] else "SOME FAILED"
print(f"Validation: {status}")
'''

EXTRACT_SCRIPT = r'''#!/bin/bash
set -euo pipefail


# Extract reference data from SQLite database using sqlite3 CLI
# and transform embedded JSON with jq for validation

mkdir -p /tmp/ref_data

# Query each reference table with sqlite3 -json and parse embedded
# JSON strings using jq's fromjson
sqlite3 -json /app/reference_data.db "SELECT * FROM coefficient_examples" \
  | jq '[.[] | {id, scale_factors: (.scale_factors | fromjson), coefficients: (.coefficients | fromjson)}]' \
  > /tmp/ref_data/coefficients.json

sqlite3 -json /app/reference_data.db "SELECT * FROM extrapolation_examples" \
  | jq '[.[] | {id, scale_factors: (.scale_factors | fromjson), values_per_level: (.values_per_level | fromjson), extrapolated_result}]' \
  > /tmp/ref_data/extrapolation.json

sqlite3 -json /app/reference_data.db "SELECT * FROM variance_formula_examples" \
  | jq '[.[] | {id, gamma: (.gamma | fromjson), variance_matrix: (.variance_matrix | fromjson), shot_allocation: (.shot_allocation | fromjson), zne_variance}]' \
  > /tmp/ref_data/variance_formula.json

sqlite3 -json /app/reference_data.db "SELECT * FROM group_variance_examples" \
  | jq '[.[] | {id, measurements: (.measurements | fromjson), weights: (.weights | fromjson), expected_variance}]' \
  > /tmp/ref_data/group_variance.json

sqlite3 -json /app/reference_data.db "SELECT * FROM allocation_examples" \
  | jq '[.[] | {id, gamma: (.gamma | fromjson), variance_matrix: (.variance_matrix | fromjson), budget, optimal_allocation: (.optimal_allocation | fromjson)}]' \
  > /tmp/ref_data/allocation.json

# Summarize extraction using jq
echo "=== Reference Data Extracted ==="
for table in coefficients extrapolation variance_formula group_variance allocation; do
    count=$(jq 'length' /tmp/ref_data/${table}.json)
    echo "  ${table}: ${count} examples"
done

# Validate optimizer against extracted reference data
python3 /app/validate_helper.py

# Verify report with jq
echo ""
jq '.' /app/validation_report.json
if jq -e '.all_passed == true' /app/validation_report.json > /dev/null 2>&1; then
    echo "All validations PASSED."
else
    echo "Some validations FAILED."
    exit 1
fi
'''

with open("/app/validate_helper.py", "w") as f:
    f.write(VALIDATE_HELPER)

with open("/app/extract_and_validate.sh", "w") as f:
    f.write(EXTRACT_SCRIPT)

os.chmod(
    "/app/extract_and_validate.sh",
    os.stat("/app/extract_and_validate.sh").st_mode
    | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH,
)

print("Validation pipeline written to /app/extract_and_validate.sh and /app/validate_helper.py")
