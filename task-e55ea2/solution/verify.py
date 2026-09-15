#!/usr/bin/env python3
"""Verify the Prolog tax engine against all 12 test cases."""

import subprocess
import sys

EXPECTED = {
    "case_01": 4196,
    "case_02": 5136,
    "case_03": 6847,
    "case_04": 62598,
    "case_05": 0,
    "case_06": 16679,
    "case_07": 5144,
    "case_08": 5282,
    "case_09": 87321,
    "case_10": 4679,
    "case_11": 3218,
    "case_12": 3542,
}

all_pass = True

for case_id, expected in sorted(EXPECTED.items()):
    goal = (
        f"consult('/app/tax_engine'), "
        f"consult('/app/cases/{case_id}'), "
        f"(compute_tax(X) -> write(X), nl ; write('ERROR'), nl), halt"
    )
    result = subprocess.run(
        ["swipl", "-g", goal, "-t", "halt"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"FAIL: {case_id} — Prolog error (exit {result.returncode})")
        print(f"  stderr: {result.stderr.strip()}")
        all_pass = False
        continue

    output = result.stdout.strip()
    if output == "ERROR":
        print(f"FAIL: {case_id} — compute_tax/1 failed")
        all_pass = False
        continue

    try:
        actual = int(float(output))
    except ValueError:
        print(f"FAIL: {case_id} — unexpected output: {output!r}")
        all_pass = False
        continue

    if actual == expected:
        print(f"PASS: {case_id} = {actual}")
    else:
        print(f"FAIL: {case_id} — expected {expected}, got {actual}")
        all_pass = False

if all_pass:
    print("\nAll 12 cases passed.")
else:
    print("\nSome cases failed.")
    sys.exit(1)
