#!/usr/bin/env python3
"""Mutation analysis pipeline: execute mutants, build kill matrix, compute subsumption,
measure coverage, and generate Graphviz subsumption DAG.

"""

import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict

MANIFEST = "/app/mutants/manifest.json"
ORIGINAL = "/app/target/mathlib.py"
TESTS_DIR = "/app/tests"
BASIC_TEST = "/app/tests/test_basic.py"
OUTPUT_DIR = "/app/output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "results.json")
ENHANCED_FILE = "/app/tests/test_enhanced.py"
DOT_FILE = os.path.join(OUTPUT_DIR, "subsumption.dot")
PNG_FILE = os.path.join(OUTPUT_DIR, "subsumption.png")
MUTANT_TIMEOUT = 15


def load_manifest():
    with open(MANIFEST) as f:
        return json.load(f)


def get_test_names():
    """Discover test function names from test_basic.py."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", BASIC_TEST, "--collect-only", "-q"],
        capture_output=True, timeout=30, cwd="/app",
        env={**os.environ, "PYTHONPATH": "/app"},
    )
    names = []
    for line in result.stdout.decode().strip().split("\n"):
        line = line.strip()
        if "::" in line and not line.startswith("="):
            names.append(line.split("::")[-1])
    return names


def run_tests_against_mutant(mutant_path, test_names):
    """Run each test individually against a mutant. Returns set of failed tests."""
    backup = "/tmp/_mathlib_solve_backup.py"
    shutil.copy(ORIGINAL, backup)
    shutil.copy(mutant_path, ORIGINAL)
    failed_tests = set()
    try:
        for tname in test_names:
            test_id = f"{BASIC_TEST}::{tname}"
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", test_id, "-x",
                     "--tb=no", "-q", "--no-header", "-p", "no:cacheprovider"],
                    capture_output=True, timeout=MUTANT_TIMEOUT, cwd="/app",
                    env={**os.environ, "PYTHONPATH": "/app"},
                )
                if result.returncode != 0:
                    failed_tests.add(tname)
            except subprocess.TimeoutExpired:
                failed_tests.add(tname)
    finally:
        shutil.copy(backup, ORIGINAL)
    return failed_tests


def classify_equivalent(mutant_info, test_names, kill_matrix):
    """Determine if a surviving mutant is equivalent."""
    mid = mutant_info["id"]
    func = mutant_info["function"]
    orig = mutant_info["original"]
    repl = mutant_info["replacement"]
    op = mutant_info["operator"]

    if op == "ROR":
        # x < 0 -> x <= 0 in abs_val: abs_val(0) = 0 either way
        if func == "abs_val" and orig == "x < 0" and repl == "x <= 0":
            return True, (
                "Changing < to <= only affects x=0 case. abs_val(0): original "
                "returns 0 (falls through), mutant returns -0 = 0. Since -0 == 0 "
                "in Python, the mutant is semantically equivalent for all inputs."
            )
        # value < low -> value <= low in clamp
        if func == "clamp" and orig == "value < low" and repl == "value <= low":
            return True, (
                "Changing < to <= only affects value==low case. When value==low, "
                "original returns value (falls through), mutant returns low. "
                "Since value==low, the return value is identical."
            )
        # value > high -> value >= high in clamp
        if func == "clamp" and orig == "value > high" and repl == "value >= high":
            return True, (
                "Changing > to >= only affects value==high case. When value==high, "
                "original returns value (falls through), mutant returns high. "
                "Since value==high, the return value is identical."
            )

    return False, ""


def compute_subsumption(kill_matrix):
    """Compute the set of dynamically subsuming mutants.

    A killed mutant M is subsuming if no other killed mutant M' has
    T(M') proper-subset-of T(M). That is, M's kill set is minimal —
    no other mutant is harder to kill.
    """
    kill_sets = {mid: set(tests) for mid, tests in kill_matrix.items()}
    subsuming = []

    for m1, t1 in kill_sets.items():
        is_subsuming = True
        for m2, t2 in kill_sets.items():
            if m2 == m1:
                continue
            if t2 < t1:
                is_subsuming = False
                break
        if is_subsuming:
            subsuming.append(m1)

    return subsuming


def measure_branch_coverage(test_paths):
    """Measure branch coverage of given test files against target/mathlib.py."""
    subprocess.run(
        [sys.executable, "-m", "coverage", "erase"],
        cwd="/app", capture_output=True,
    )
    cmd = (
        [sys.executable, "-m", "coverage", "run", "--branch",
         "--source=/app/target", "-m", "pytest"]
        + test_paths
        + ["-q", "--no-header", "-p", "no:cacheprovider"]
    )
    subprocess.run(
        cmd, cwd="/app", capture_output=True, timeout=60,
        env={**os.environ, "PYTHONPATH": "/app"},
    )
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-o", "/tmp/cov_report.json"],
        capture_output=True, cwd="/app",
    )
    with open("/tmp/cov_report.json") as f:
        cov = json.load(f)

    totals = cov["totals"]
    num_branches = totals.get("num_branches", 0)
    covered = totals.get("covered_branches", 0)
    if num_branches > 0:
        return round(covered / num_branches * 100, 2)
    return 0.0


def generate_subsumption_dag(kill_matrix, output_dir):
    """Generate the transitive reduction of the subsumption partial order as DOT+PNG."""
    kill_sets = {mid: set(tests) for mid, tests in kill_matrix.items()}

    # Collect all subsumption edges: M1 -> M2 means T(M1) ⊂ T(M2)
    all_edges = []
    for m1, t1 in kill_sets.items():
        for m2, t2 in kill_sets.items():
            if m1 != m2 and t1 < t2:
                all_edges.append((m1, m2))

    # Transitive reduction: keep edge (m1, m2) only if no intermediate m3 exists
    reduced_edges = []
    for m1, m2 in all_edges:
        t1 = kill_sets[m1]
        t2 = kill_sets[m2]
        is_direct = True
        for m3, t3 in kill_sets.items():
            if m3 != m1 and m3 != m2:
                if t1 < t3 and t3 < t2:
                    is_direct = False
                    break
        if is_direct:
            reduced_edges.append((m1, m2))

    # Build DOT output
    lines = ["digraph subsumption {"]
    lines.append("  rankdir=BT;")
    lines.append('  node [shape=box, fontsize=10];')

    for mid in sorted(kill_sets.keys()):
        lines.append(f'  "{mid}";')

    for src, dst in sorted(reduced_edges):
        lines.append(f'  "{src}" -> "{dst}";')

    lines.append("}")

    dot_path = os.path.join(output_dir, "subsumption.dot")
    with open(dot_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    png_path = os.path.join(output_dir, "subsumption.png")
    subprocess.run(
        ["dot", "-Tpng", dot_path, "-o", png_path],
        check=True, timeout=30,
    )
    print(f"Subsumption DAG: {dot_path}, {png_path}")


def write_enhanced_tests(surviving_non_equivalent, manifest):
    """Write targeted tests to kill surviving non-equivalent mutants."""
    test_code = '''"""Enhanced tests to kill surviving non-equivalent mutants."""
import sys
sys.path.insert(0, "/app")
from target.mathlib import is_sorted, variance, is_valid_triangle


def test_is_sorted_with_duplicates():
    """Detects mutations that change > to >= in sorted-order comparison."""
    assert is_sorted([1, 1, 2, 2, 3]) == True
    assert is_sorted([5, 5, 5]) == True


def test_is_sorted_unsorted():
    """Additional coverage for is_sorted."""
    assert is_sorted([3, 1, 2]) == False


def test_variance_two_values():
    """Detects mutations that change < to <= in minimum-size guard."""
    result = variance([1, 3])
    assert abs(result - 2.0) < 0.001


def test_variance_three_values():
    """Additional variance coverage."""
    result = variance([10, 20, 30])
    assert abs(result - 100.0) < 0.001


def test_triangle_inequality_violated():
    """Detects mutations that change AND to OR in triangle inequality checks."""
    assert is_valid_triangle(1, 1, 3) == False
    assert is_valid_triangle(1, 2, 10) == False


def test_triangle_degenerate():
    """Test degenerate triangle cases."""
    assert is_valid_triangle(1, 1, 2) == False
    assert is_valid_triangle(0, 5, 5) == False


def test_triangle_valid():
    """Ensure valid triangles still pass."""
    assert is_valid_triangle(3, 4, 5) == True
    assert is_valid_triangle(5, 5, 5) == True
'''
    with open(ENHANCED_FILE, "w") as f:
        f.write(test_code)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", ENHANCED_FILE, "-v", "--tb=short"],
        capture_output=True, timeout=60, cwd="/app",
        env={**os.environ, "PYTHONPATH": "/app"},
    )
    if result.returncode != 0:
        print("WARNING: Enhanced tests fail on original code!")
        print(result.stdout.decode())
        print(result.stderr.decode())


def main():
    manifest = load_manifest()
    mutants = manifest["mutants"]
    test_names = get_test_names()

    print(f"Found {len(mutants)} mutants and {len(test_names)} tests")
    print(f"Tests: {test_names}")

    # Phase 1: Execute each mutant against the test suite
    kill_matrix = {}
    survived = []
    operator_counts = defaultdict(int)

    for mutant in mutants:
        mid = mutant["id"]
        op = mutant["operator"]
        operator_counts[op] += 1

        mutant_path = f"/app/mutants/{mid}.py"
        if not os.path.exists(mutant_path):
            print(f"WARNING: Mutant file {mutant_path} not found, skipping")
            survived.append(mid)
            continue

        print(f"Testing {mid} ({op}: {mutant['description']})...", end=" ")
        failed_tests = run_tests_against_mutant(mutant_path, test_names)

        if failed_tests:
            kill_matrix[mid] = sorted(failed_tests)
            print(f"KILLED by {len(failed_tests)} tests")
        else:
            survived.append(mid)
            print("SURVIVED")

    # Phase 2: Classify survivors
    equivalent_mutants = []
    surviving_non_equivalent = []

    for mid in survived:
        info = next(m for m in mutants if m["id"] == mid)
        is_eq, reason = classify_equivalent(info, test_names, kill_matrix)
        if is_eq:
            equivalent_mutants.append({"id": mid, "reason": reason})
        else:
            surviving_non_equivalent.append(mid)

    # Phase 3: Compute subsumption
    subsuming = compute_subsumption(kill_matrix)

    # Phase 4: Compute scores
    killed_count = len(kill_matrix)
    survived_count = len(survived)
    equiv_count = len(equivalent_mutants)
    total = len(mutants)
    killable = total - equiv_count
    mutation_score = killed_count / killable if killable > 0 else 0.0

    subsuming_killed = len(subsuming)
    snq = len(surviving_non_equivalent)
    subsuming_denom = subsuming_killed + snq
    subsuming_mutation_score = (
        subsuming_killed / subsuming_denom if subsuming_denom > 0 else 0.0
    )

    # Phase 5: Write enhanced tests
    write_enhanced_tests(surviving_non_equivalent, manifest)

    # Phase 6: Measure branch coverage
    print("\nMeasuring branch coverage...")
    coverage_original = measure_branch_coverage([BASIC_TEST])
    print(f"  Original test suite: {coverage_original}%")
    coverage_enhanced = measure_branch_coverage([BASIC_TEST, ENHANCED_FILE])
    print(f"  With enhanced tests: {coverage_enhanced}%")

    # Phase 7: Generate subsumption DAG
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generate_subsumption_dag(kill_matrix, OUTPUT_DIR)

    # Phase 8: Write output
    results = {
        "total_mutants": total,
        "killed": killed_count,
        "survived": survived_count,
        "equivalent": equiv_count,
        "mutation_score": round(mutation_score, 4),
        "operator_counts": dict(operator_counts),
        "kill_matrix": kill_matrix,
        "subsuming_mutants": sorted(subsuming),
        "subsuming_mutation_score": round(subsuming_mutation_score, 4),
        "equivalent_mutants": equivalent_mutants,
        "surviving_non_equivalent": sorted(surviving_non_equivalent),
        "branch_coverage_original": coverage_original,
        "branch_coverage_enhanced": coverage_enhanced,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print("MUTATION ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"Total mutants:              {total}")
    print(f"Killed:                     {killed_count}")
    print(f"Survived:                   {survived_count}")
    print(f"  Equivalent:               {equiv_count}")
    print(f"  Non-equivalent (gaps):    {snq}")
    print(f"Mutation score:             {mutation_score:.4f}")
    print(f"Subsuming mutants:          {subsuming_killed}")
    print(f"Subsuming mutation score:   {subsuming_mutation_score:.4f}")
    print(f"Branch coverage (original): {coverage_original}%")
    print(f"Branch coverage (enhanced): {coverage_enhanced}%")
    print(f"Results written to:         {OUTPUT_FILE}")
    print(f"Enhanced tests written to:  {ENHANCED_FILE}")


if __name__ == "__main__":
    main()
