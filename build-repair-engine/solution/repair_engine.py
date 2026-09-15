#!/usr/bin/env python3
"""
Spectrum-based fault localization and mutation-based automated program repair engine.

Implements:
  - gcov-based per-test line coverage collection
  - Ochiai suspiciousness metric for fault localization
  - Mutation operators: relational replacement, arithmetic replacement,
    constant modification, array index adjustment
  - Compile-test patch validation loop
"""

import os
import sys
import re
import json
import math
import shutil
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def build_with_coverage(subject_dir):
    subprocess.run(["make", "clean"], cwd=subject_dir, capture_output=True)
    r = subprocess.run(
        ["make", "CFLAGS=-fprofile-arcs -ftest-coverage -g -O0"],
        cwd=subject_dir, capture_output=True,
    )
    return r.returncode == 0


def build_normal(subject_dir):
    subprocess.run(["make", "clean"], cwd=subject_dir, capture_output=True)
    r = subprocess.run(["make"], cwd=subject_dir, capture_output=True)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def run_single_test(subject_dir, idx):
    try:
        r = subprocess.run(
            ["./test_driver", str(idx)],
            cwd=subject_dir, capture_output=True, timeout=10,
        )
        out = r.stdout.decode(errors="replace")
        return "PASS" in out, out
    except (subprocess.TimeoutExpired, OSError):
        return False, ""


def run_all_tests(subject_dir):
    try:
        r = subprocess.run(
            ["./test_driver"],
            cwd=subject_dir, capture_output=True, timeout=30,
        )
        out = r.stdout.decode(errors="replace")
        results = []
        for line in out.strip().splitlines():
            if line.startswith("PASS:"):
                results.append(True)
            elif line.startswith("FAIL:"):
                results.append(False)
        return results, r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return [], False


def count_tests(subject_dir):
    results, _ = run_all_tests(subject_dir)
    return len(results)


# ---------------------------------------------------------------------------
# Coverage collection (gcov)
# ---------------------------------------------------------------------------

def reset_gcda(subject_dir):
    for f in Path(subject_dir).glob("*.gcda"):
        f.unlink()


def collect_gcov(subject_dir, source="buggy.c"):
    # gcda/gcno files are prefixed with the executable name (test_driver-)
    gcda = os.path.join(subject_dir, "test_driver-" + source.replace(".c", ".gcda"))
    if os.path.exists(gcda):
        subprocess.run(["gcov", gcda], cwd=subject_dir, capture_output=True)
    else:
        subprocess.run(["gcov", source], cwd=subject_dir, capture_output=True)
    gcov_path = os.path.join(subject_dir, source + ".gcov")
    cov = {}
    if not os.path.exists(gcov_path):
        return cov
    with open(gcov_path) as fh:
        for line in fh:
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            cnt = parts[0].strip()
            try:
                lineno = int(parts[1].strip())
            except ValueError:
                continue
            if lineno == 0:
                continue
            if cnt == "-":
                cov[lineno] = -1
            elif cnt == "#####" or cnt == "=====":
                cov[lineno] = 0
            else:
                try:
                    cov[lineno] = int(cnt)
                except ValueError:
                    cov[lineno] = 0
    return cov


# ---------------------------------------------------------------------------
# Spectrum-based fault localization (Ochiai)
# ---------------------------------------------------------------------------

def fault_localize(subject_dir, n_tests):
    coverages = []
    test_pass = []

    for t in range(n_tests):
        reset_gcda(subject_dir)
        passed, _ = run_single_test(subject_dir, t)
        cov = collect_gcov(subject_dir)
        coverages.append(cov)
        test_pass.append(passed)

    all_lines = set()
    for c in coverages:
        for ln, v in c.items():
            if v >= 0:
                all_lines.add(ln)

    total_fail = sum(1 for p in test_pass if not p)

    scores = {}
    for ln in all_lines:
        ef = ep = 0
        for t in range(n_tests):
            covered = coverages[t].get(ln, 0) > 0
            if covered and not test_pass[t]:
                ef += 1
            elif covered and test_pass[t]:
                ep += 1
        denom = math.sqrt(total_fail * (ef + ep)) if total_fail * (ef + ep) > 0 else 0
        scores[ln] = ef / denom if denom else 0.0

    return sorted(scores.items(), key=lambda x: -x[1])


# ---------------------------------------------------------------------------
# Mutation operators
# ---------------------------------------------------------------------------

_REL_OPS = [" < ", " <= ", " > ", " >= ", " == ", " != "]


def _relational_mutations(line):
    muts = []
    for old in _REL_OPS:
        if old not in line:
            continue
        for new in _REL_OPS:
            if new == old:
                continue
            muts.append(line.replace(old, new, 1))
    return muts


def _arithmetic_mutations(line):
    muts = []
    pairs = [
        (" + ", " - "), (" - ", " + "),
        (" * ", " / "), (" / ", " * "),
    ]
    for old, new in pairs:
        if old in line:
            muts.append(line.replace(old, new, 1))
    return muts


def _constant_mutations(line):
    muts = []
    # 0 -> 1
    for tok in [" 0)", " 0;", " 0,", " 0 "]:
        if tok in line:
            muts.append(line.replace(tok, tok.replace("0", "1"), 1))
    # 1 -> 0, 1 -> 2
    for tok in [" 1)", " 1;", " 1,", " 1 "]:
        if tok in line:
            muts.append(line.replace(tok, tok.replace("1", "0"), 1))
            muts.append(line.replace(tok, tok.replace("1", "2"), 1))
    return muts


def _index_mutations(line):
    muts = []
    # [var] -> [var-1], [var+1]
    for m in re.finditer(r"\[(\w+)\]", line):
        var = m.group(1)
        if var.isdigit():
            continue
        muts.append(line[: m.start()] + f"[{var}-1]" + line[m.end() :])
        muts.append(line[: m.start()] + f"[{var}+1]" + line[m.end() :])
    # [var-1] -> [var]
    for m in re.finditer(r"\[(\w+)-1\]", line):
        var = m.group(1)
        muts.append(line[: m.start()] + f"[{var}]" + line[m.end() :])
    # [var+1] -> [var]
    for m in re.finditer(r"\[(\w+)\+1\]", line):
        var = m.group(1)
        muts.append(line[: m.start()] + f"[{var}]" + line[m.end() :])
    return muts


def generate_mutations(line):
    # Use ordered list so relational mutations (most common fix) are tried first
    muts = []
    seen = set()
    for group in [
        _relational_mutations(line),
        _constant_mutations(line),
        _index_mutations(line),
        _arithmetic_mutations(line),
    ]:
        for m in group:
            if m != line and m not in seen:
                muts.append(m)
                seen.add(m)
    return muts


# ---------------------------------------------------------------------------
# Repair loop
# ---------------------------------------------------------------------------

def repair_subject(subject_dir):
    buggy = os.path.join(subject_dir, "buggy.c")
    backup = buggy + ".bak"
    shutil.copy2(buggy, backup)
    original = open(buggy).readlines()

    if not build_with_coverage(subject_dir):
        print(f"  [!] build with coverage failed")
        return False

    n_tests = count_tests(subject_dir)
    print(f"  tests: {n_tests}")

    ranked = fault_localize(subject_dir, n_tests)
    top = [(ln, f"{s:.3f}") for ln, s in ranked[:10]]
    print(f"  top suspicious: {top}")

    for lineno, susp in ranked[:20]:
        if susp <= 0:
            continue
        idx = lineno - 1
        if idx < 0 or idx >= len(original):
            continue
        src_line = original[idx]
        mutations = generate_mutations(src_line)
        for mut in mutations:
            patched = list(original)
            patched[idx] = mut
            with open(buggy, "w") as f:
                f.writelines(patched)
            if not build_normal(subject_dir):
                continue
            results, ok = run_all_tests(subject_dir)
            if ok and results and all(results) and len(results) == n_tests:
                print(f"  REPAIRED line {lineno}")
                print(f"    was: {src_line.rstrip()}")
                print(f"    now: {mut.rstrip()}")
                fixed_path = os.path.join(subject_dir, "fixed.c")
                with open(fixed_path, "w") as f:
                    f.writelines(patched)
                info = {
                    "line": lineno,
                    "original": src_line.strip(),
                    "fixed": mut.strip(),
                }
                with open(os.path.join(subject_dir, "repair.json"), "w") as f:
                    json.dump(info, f, indent=2)
                shutil.copy2(backup, buggy)
                return True

    shutil.copy2(backup, buggy)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) > 1:
        d = sys.argv[1]
        print(f"Repairing {d}")
        ok = repair_subject(d)
        sys.exit(0 if ok else 1)

    subjects_dir = "/app/subjects"
    subjects = sorted(
        s for s in os.listdir(subjects_dir)
        if os.path.isdir(os.path.join(subjects_dir, s))
    )
    n_ok = 0
    for s in subjects:
        path = os.path.join(subjects_dir, s)
        print(f"\n=== {s} ===")
        if repair_subject(path):
            n_ok += 1
    print(f"\nRepaired {n_ok}/{len(subjects)}")
    sys.exit(0 if n_ok == len(subjects) else 1)


if __name__ == "__main__":
    main()
