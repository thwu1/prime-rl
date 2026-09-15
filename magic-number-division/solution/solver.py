#!/usr/bin/env python3
"""
Audit, evaluate severity, and remediate optimized division/modulo functions.

Strategy:
  1. Load the spec to know what each function is INTENDED to compute.
  2. For each function, determine div vs mod from f(1).
  3. Find the actual divisor via binary search on positive inputs.
  4. Determine signedness by testing with a negative input.
  5. Compare against the spec, classify any bugs, find witnesses.
  6. Compute error counts mathematically for each bug.
  7. Generate corrected C source and compile a fixed binary.
  8. Write audit.json, remediation.json.
"""

import subprocess
import json
import sys
import os


def run_challenge(idx, val):
    result = subprocess.run(
        ["/app/challenge", str(idx), str(val)],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"Binary error for func {idx}, val {val}: {result.stderr}")
    return int(result.stdout.strip())


def c_trunc_div(x, d):
    if x >= 0:
        return x // d
    else:
        return -((-x) // d)


def c_trunc_mod(x, d):
    return x - c_trunc_div(x, d) * d


def compute_expected(op, d, val):
    if op == "sdiv":
        return c_trunc_div(val, d)
    elif op == "smod":
        return c_trunc_mod(val, d)
    elif op == "udiv":
        return (val & 0xFFFFFFFF) // d
    elif op == "umod":
        return (val & 0xFFFFFFFF) % d
    else:
        raise ValueError(f"Unknown operation: {op}")


def detect_div_vs_mod(idx):
    r1 = run_challenge(idx, 1)
    if r1 == 1:
        return "mod"
    return "div"


def find_divisor_div(idx):
    lo, hi = 1, (1 << 31) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        r = run_challenge(idx, mid)
        if r >= 1:
            hi = mid
        else:
            lo = mid + 1
    assert run_challenge(idx, lo) == 1, f"Verification failed: f({lo}) != 1"
    if lo > 1:
        assert run_challenge(idx, lo - 1) == 0, f"Verification failed: f({lo-1}) != 0"
    return lo


def find_divisor_mod(idx):
    lo, hi = 1, (1 << 31) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        r = run_challenge(idx, mid)
        if r == mid:
            lo = mid + 1
        else:
            hi = mid
    assert run_challenge(idx, lo) == 0, f"Verification failed: f({lo}) != 0"
    if lo > 1:
        assert run_challenge(idx, lo - 1) == lo - 1, \
            f"Verification failed: f({lo-1}) != {lo-1}"
    return lo


def detect_signedness(idx, op_type, divisor):
    for test_val in [-1000, -7777, -12345]:
        actual = run_challenge(idx, test_val)
        if op_type == "div":
            signed_exp = c_trunc_div(test_val, divisor)
            unsigned_exp = (test_val & 0xFFFFFFFF) // divisor
        else:
            signed_exp = c_trunc_mod(test_val, divisor)
            unsigned_exp = (test_val & 0xFFFFFFFF) % divisor
        if signed_exp != unsigned_exp:
            if actual == signed_exp:
                return "signed"
            if actual == unsigned_exp:
                return "unsigned"
            unsigned_as_signed = unsigned_exp
            if unsigned_exp >= (1 << 31):
                unsigned_as_signed = unsigned_exp - (1 << 32)
            if actual == unsigned_as_signed:
                return "unsigned"
            continue
    r = run_challenge(idx, -1)
    if r > 1000:
        return "unsigned"
    return "signed"


def find_witness(idx, spec_op, spec_div):
    test_values = list(range(-1000, 1001))
    test_values += [-2**31, -2**31 + 1, 2**31 - 1, 2**31 - 2]
    test_values += [spec_div - 1, spec_div, spec_div + 1, -spec_div, -(spec_div + 1)]
    for val in test_values:
        actual = run_challenge(idx, val)
        expected = compute_expected(spec_op, spec_div, val)
        if actual != expected:
            return val
    return -999999


def classify_bug(idx, spec_op, spec_div, actual_op, actual_div):
    if actual_div == spec_div and actual_op[1:] == spec_op[1:] and actual_op[0] != spec_op[0]:
        return "signedness_mismatch"
    if actual_div == spec_div and actual_op[0] == spec_op[0] and actual_op[1:] != spec_op[1:]:
        return "wrong_operation"
    if actual_op == spec_op and actual_div != spec_div:
        return "wrong_divisor"
    if actual_op[1:] == spec_op[1:]:
        return "signedness_mismatch"
    if actual_op[0] == spec_op[0]:
        if actual_div != spec_div:
            return "wrong_divisor"
        return "wrong_operation"
    return "wrong_operation"


def analyze_function(idx, spec):
    spec_op = spec["intended_operation"]
    spec_div = spec["intended_divisor"]
    print(f"\n=== Analyzing function {idx} ===", file=sys.stderr)
    print(f"  Spec: {spec_op} by {spec_div}", file=sys.stderr)

    op_type = detect_div_vs_mod(idx)
    print(f"  Operation type: {op_type}", file=sys.stderr)

    if op_type == "div":
        actual_div = find_divisor_div(idx)
    else:
        actual_div = find_divisor_mod(idx)
    print(f"  Actual divisor: {actual_div}", file=sys.stderr)

    signedness = detect_signedness(idx, op_type, actual_div)
    print(f"  Signedness: {signedness}", file=sys.stderr)

    prefix = "s" if signedness == "signed" else "u"
    actual_op = f"{prefix}{op_type}"
    print(f"  Actual operation: {actual_op}", file=sys.stderr)

    if actual_op == spec_op and actual_div == spec_div:
        print(f"  Verdict: CORRECT", file=sys.stderr)
        return {
            "func_index": idx,
            "verdict": "correct",
            "actual_operation": actual_op,
            "actual_divisor": actual_div,
        }
    else:
        bug_cat = classify_bug(idx, spec_op, spec_div, actual_op, actual_div)
        print(f"  Verdict: BUGGY ({bug_cat})", file=sys.stderr)
        witness = find_witness(idx, spec_op, spec_div)
        print(f"  Witness input: {witness}", file=sys.stderr)
        return {
            "func_index": idx,
            "verdict": "buggy",
            "actual_operation": actual_op,
            "actual_divisor": actual_div,
            "bug_category": bug_cat,
            "witness_input": witness,
        }


# ===================================================================
# Error count computation (mathematical, not brute-force)
# ===================================================================

def count_sdiv_agreements(d1, d2):
    """Count x in [-2^31, 2^31-1] where trunc(x/d1) = trunc(x/d2).
    Both d1, d2 > 0. Uses quotient-interval overlap analysis."""
    d_lo = min(d1, d2)
    d_hi = max(d1, d2)

    # Count non-negative agreements (x >= 0)
    pos_count = 0
    q = 0
    while True:
        lo = d_hi * q
        hi = d_lo * q + d_lo - 1
        if lo > hi:
            break
        if lo > 2**31 - 1:
            break
        hi = min(hi, 2**31 - 1)
        pos_count += hi - lo + 1
        q += 1

    # For negative x: sdiv(x,d) = -sdiv(-x,d), so agreements mirror positive y>0.
    # Negative agreement count = (positive agreements) - 1 (exclude y=0).
    neg_count = pos_count - 1

    return pos_count + neg_count


def compute_error_count(bug_category, actual_op, actual_div, spec_op, spec_div):
    """Compute the exact number of 32-bit signed inputs producing wrong output."""
    total = 2**32

    if bug_category == "signedness_mismatch":
        # Signed vs unsigned agree on non-negative inputs, disagree on all negative.
        return 2**31

    elif bug_category == "wrong_divisor":
        # Same operation type, different divisor.
        agreements = count_sdiv_agreements(actual_div, spec_div)
        return total - agreements

    elif bug_category == "wrong_operation":
        # sdiv(x,d) vs smod(x,d). They agree when x = (d+1)*q, |q| < d.
        # Proof: x = d*q + r, need q = r, so x = d*q + q = (d+1)*q.
        # |q| < d since |r| < d. Agreement count = 2*d - 1.
        d = actual_div  # = spec_div for wrong_operation
        agreement_count = 2 * d - 1
        return total - agreement_count

    else:
        raise ValueError(f"Unknown bug category: {bug_category}")


def compute_severity(error_count):
    """Assign severity based on fraction of 32-bit signed input space affected."""
    total = 2**32
    fraction = error_count / total
    if fraction > 0.25:
        return "critical"
    elif fraction > 0.01:
        return "high"
    elif fraction > 0.0001:
        return "medium"
    else:
        return "low"


# ===================================================================
# Fixed binary generation
# ===================================================================

def generate_fixed_source(specs):
    """Generate corrected C source implementing all functions per spec."""
    lines = ['#include <stdio.h>', '#include <stdlib.h>', '']

    for spec in sorted(specs, key=lambda s: s['func_index']):
        idx = spec['func_index']
        op = spec['intended_operation']
        d = spec['intended_divisor']

        if op == 'sdiv':
            lines.append(
                f'__attribute__((noinline)) int func{idx}(int x) '
                f'{{ return x / {d}; }}')
        elif op == 'udiv':
            lines.append(
                f'__attribute__((noinline)) unsigned func{idx}(unsigned x) '
                f'{{ return x / {d}u; }}')
        elif op == 'smod':
            lines.append(
                f'__attribute__((noinline)) int func{idx}(int x) '
                f'{{ return x % {d}; }}')
        elif op == 'umod':
            lines.append(
                f'__attribute__((noinline)) unsigned func{idx}(unsigned x) '
                f'{{ return x % {d}u; }}')

    lines.append('')
    lines.append('int main(int argc, char *argv[]) {')
    lines.append('    if (argc < 3) {')
    lines.append('        fprintf(stderr, "Usage: %s <func_index> <value>\\n", argv[0]);')
    lines.append('        return 1;')
    lines.append('    }')
    lines.append('    int idx = atoi(argv[1]);')
    lines.append('    long long val = atoll(argv[2]);')
    lines.append('    switch (idx) {')

    for spec in sorted(specs, key=lambda s: s['func_index']):
        idx = spec['func_index']
        op = spec['intended_operation']
        if op in ('sdiv', 'smod'):
            lines.append(
                f'        case {idx}: printf("%d\\n", func{idx}((int)val)); break;')
        else:
            lines.append(
                f'        case {idx}: printf("%u\\n", func{idx}((unsigned)val)); break;')

    lines.append('        default: fprintf(stderr, "Unknown function index\\n"); return 1;')
    lines.append('    }')
    lines.append('    return 0;')
    lines.append('}')

    return '\n'.join(lines) + '\n'


def build_fixed_binary(specs):
    """Write corrected C source and compile to /app/challenge_fixed."""
    source = generate_fixed_source(specs)
    src_path = '/app/challenge_fixed.c'

    with open(src_path, 'w') as f:
        f.write(source)

    result = subprocess.run(
        ['gcc', '-O2', '-o', '/app/challenge_fixed', src_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"Compilation failed: {result.stderr}", file=sys.stderr)
        raise RuntimeError("Failed to compile fixed binary")

    print("Fixed binary compiled successfully.", file=sys.stderr)

    # Verify a few values
    for spec in specs:
        idx = spec['func_index']
        op = spec['intended_operation']
        d = spec['intended_divisor']
        for test_val in [0, 1, d, -1 if op.startswith('s') else d + 1]:
            r = subprocess.run(
                ['/app/challenge_fixed', str(idx), str(test_val)],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"Fixed binary failed for func {idx}, val {test_val}: {r.stderr}")
            actual = int(r.stdout.strip())
            if op == "sdiv":
                expected = c_trunc_div(test_val, d)
            elif op == "smod":
                expected = c_trunc_mod(test_val, d)
            elif op == "udiv":
                expected = (test_val & 0xFFFFFFFF) // d
            elif op == "umod":
                expected = (test_val & 0xFFFFFFFF) % d
            if actual != expected:
                raise RuntimeError(
                    f"Fixed binary wrong for func {idx}, val {test_val}: "
                    f"got {actual}, expected {expected}")

    print("Fixed binary verification passed.", file=sys.stderr)


# ===================================================================
# Main
# ===================================================================

def main():
    with open("/app/spec.json") as f:
        specs = json.load(f)
    spec_by_idx = {s["func_index"]: s for s in specs}

    # Part 1: Audit
    results = []
    for idx in range(8):
        result = analyze_function(idx, spec_by_idx[idx])
        results.append(result)
    results.sort(key=lambda x: x["func_index"])

    with open("/app/audit.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n=== Audit complete ===", file=sys.stderr)
    for r in results:
        v = r["verdict"]
        op = r["actual_operation"]
        d = r["actual_divisor"]
        if v == "buggy":
            cat = r["bug_category"]
            w = r["witness_input"]
            print(f"  func {r['func_index']}: {v} ({cat}) -- actual {op}/{d}, witness={w}",
                  file=sys.stderr)
        else:
            print(f"  func {r['func_index']}: {v} -- {op}/{d}", file=sys.stderr)

    # Part 2: Severity evaluation
    print("\n=== Severity evaluation ===", file=sys.stderr)
    bug_entries = []
    for r in results:
        if r["verdict"] == "buggy":
            idx = r["func_index"]
            spec = spec_by_idx[idx]
            error_count = compute_error_count(
                r["bug_category"],
                r["actual_operation"], r["actual_divisor"],
                spec["intended_operation"], spec["intended_divisor"]
            )
            severity = compute_severity(error_count)
            bug_entries.append({
                "func_index": idx,
                "severity": severity,
                "error_count": error_count,
            })
            print(f"  func {idx}: error_count={error_count}, severity={severity}",
                  file=sys.stderr)

    # Rank by error_count descending, then func_index ascending
    bug_entries.sort(key=lambda b: (-b["error_count"], b["func_index"]))
    for rank, entry in enumerate(bug_entries, 1):
        entry["priority_rank"] = rank

    remediation = {"bugs": bug_entries}
    with open("/app/remediation.json", "w") as f:
        json.dump(remediation, f, indent=2)

    print("\n=== Remediation priorities ===", file=sys.stderr)
    for entry in bug_entries:
        print(f"  P{entry['priority_rank']}: func {entry['func_index']} "
              f"({entry['severity']}, {entry['error_count']} errors)", file=sys.stderr)

    # Part 3: Build corrected binary
    print("\n=== Building corrected binary ===", file=sys.stderr)
    build_fixed_binary(specs)

    print("\n=== All deliverables complete ===", file=sys.stderr)


if __name__ == "__main__":
    main()
