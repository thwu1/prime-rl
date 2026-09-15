"""Verification tests for mutation analysis task.

"""

import json
import os
import re
import shutil
import subprocess
import sys

RESULTS_PATH = "/app/output/results.json"
ENHANCED_TESTS = "/app/tests/test_enhanced.py"
ORIGINAL_MATHLIB = "/app/target/mathlib.py"
SUBSUMPTION_DOT = "/app/output/subsumption.dot"
SUBSUMPTION_PNG = "/app/output/subsumption.png"

REQUIRED_KEYS = [
    "total_mutants", "killed", "survived", "equivalent",
    "mutation_score", "operator_counts", "kill_matrix",
    "subsuming_mutants", "subsuming_mutation_score",
    "equivalent_mutants", "surviving_non_equivalent",
    "branch_coverage_original", "branch_coverage_enhanced",
]

REQUIRED_OPERATORS = ["AOR", "ROR", "LCR", "AOD", "UOI"]

# Known ground truth
KNOWN_EQUIVALENT_IDS = {"M001", "M005", "M007"}
TOTAL_MUTANTS = 34


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def test_output_file_exists():
    """Output results file must exist."""
    assert os.path.exists(RESULTS_PATH), f"Missing {RESULTS_PATH}"


def test_output_valid_json():
    """Output must be valid JSON."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_output_has_required_keys():
    """Output JSON must contain all required fields."""
    data = load_results()
    for key in REQUIRED_KEYS:
        assert key in data, f"Missing required key: {key}"


def test_total_mutants():
    """Total mutant count must match the manifest."""
    data = load_results()
    assert data["total_mutants"] == TOTAL_MUTANTS, (
        f"Expected {TOTAL_MUTANTS} mutants, got {data['total_mutants']}"
    )


def test_count_consistency():
    """killed + survived must equal total_mutants."""
    data = load_results()
    assert data["killed"] + data["survived"] == data["total_mutants"], (
        f"killed({data['killed']}) + survived({data['survived']}) "
        f"!= total({data['total_mutants']})"
    )


def test_survived_breakdown():
    """equivalent + len(surviving_non_equivalent) must equal survived."""
    data = load_results()
    snq = len(data["surviving_non_equivalent"])
    assert data["equivalent"] + snq == data["survived"], (
        f"equivalent({data['equivalent']}) + surviving_non_eq({snq}) "
        f"!= survived({data['survived']})"
    )


def test_mutation_score():
    """Mutation score must be correctly computed."""
    data = load_results()
    killable = data["total_mutants"] - data["equivalent"]
    if killable > 0:
        expected = data["killed"] / killable
        assert abs(data["mutation_score"] - expected) < 0.01, (
            f"mutation_score {data['mutation_score']} != "
            f"killed/killable = {data['killed']}/{killable} = {expected}"
        )


def test_operator_counts_present():
    """All five operator types must appear in operator_counts."""
    data = load_results()
    counts = data["operator_counts"]
    for op in REQUIRED_OPERATORS:
        assert op in counts, f"Missing operator type: {op}"
        assert isinstance(counts[op], int), f"Operator count for {op} must be int"
        assert counts[op] >= 0, f"Operator count for {op} must be non-negative"


def test_operator_counts_sum():
    """Operator counts must sum to total_mutants."""
    data = load_results()
    total = sum(data["operator_counts"].values())
    assert total == data["total_mutants"], (
        f"Operator counts sum {total} != total_mutants {data['total_mutants']}"
    )


def test_kill_matrix_structure():
    """Kill matrix must map mutant IDs to non-empty lists of test names."""
    data = load_results()
    km = data["kill_matrix"]
    assert isinstance(km, dict), "kill_matrix must be a dict"
    assert len(km) == data["killed"], (
        f"kill_matrix has {len(km)} entries but killed={data['killed']}"
    )
    for mid, tests in km.items():
        assert isinstance(tests, list), f"kill_matrix[{mid}] must be a list"
        assert len(tests) > 0, f"kill_matrix[{mid}] must be non-empty"
        for t in tests:
            assert isinstance(t, str), f"Test names must be strings in {mid}"


def test_kill_matrix_no_survivors():
    """Survived mutants must not appear in the kill matrix."""
    data = load_results()
    km_ids = set(data["kill_matrix"].keys())
    equiv_ids = {e["id"] for e in data["equivalent_mutants"]}
    survived_ids = set(data["surviving_non_equivalent"])
    for sid in equiv_ids | survived_ids:
        assert sid not in km_ids, f"Survived/equivalent mutant {sid} in kill_matrix"


def test_equivalent_mutants_structure():
    """Equivalent mutants must have id and reason fields."""
    data = load_results()
    for entry in data["equivalent_mutants"]:
        assert "id" in entry, "Equivalent mutant entry missing 'id'"
        assert "reason" in entry, "Equivalent mutant entry missing 'reason'"
        assert isinstance(entry["reason"], str), "Reason must be a string"
        assert len(entry["reason"]) > 10, (
            f"Reason for {entry['id']} too short - provide substantive justification"
        )


def test_known_equivalents_identified():
    """Known equivalent mutants (M001, M005, M007) should be classified as equivalent."""
    data = load_results()
    identified = {e["id"] for e in data["equivalent_mutants"]}
    for eid in KNOWN_EQUIVALENT_IDS:
        assert eid in identified, (
            f"Known equivalent mutant {eid} not classified as equivalent. "
            f"Identified equivalents: {identified}"
        )


def test_minimum_killed():
    """At least 25 mutants should be killed by the test suite."""
    data = load_results()
    assert data["killed"] >= 25, (
        f"Expected at least 25 killed mutants, got {data['killed']}"
    )


def test_subsuming_mutants_valid():
    """Subsuming mutants must be a subset of killed mutants."""
    data = load_results()
    subsuming = set(data["subsuming_mutants"])
    killed = set(data["kill_matrix"].keys())
    assert subsuming.issubset(killed), (
        f"Subsuming mutants not in killed set: {subsuming - killed}"
    )
    assert len(subsuming) > 0, "Subsuming set must not be empty"


def test_subsuming_antichain():
    """No subsuming mutant's kill set should be a proper superset of another's."""
    data = load_results()
    km = data["kill_matrix"]
    subsuming = data["subsuming_mutants"]
    for m1 in subsuming:
        t1 = set(km[m1])
        for m2 in km:
            if m2 == m1:
                continue
            t2 = set(km[m2])
            if t2 < t1:
                assert False, (
                    f"Subsuming mutant {m1} has kill set {t1} which is a proper "
                    f"superset of killed mutant {m2}'s kill set {t2}. "
                    f"{m1} should NOT be subsuming."
                )


def test_subsuming_mutation_score_range():
    """Subsuming mutation score must be between 0 and 1."""
    data = load_results()
    score = data["subsuming_mutation_score"]
    assert 0.0 <= score <= 1.0, (
        f"subsuming_mutation_score {score} out of range [0, 1]"
    )


# --- Branch coverage tests ---


def test_branch_coverage_fields():
    """Branch coverage metrics must be present and reasonable."""
    data = load_results()
    orig = data["branch_coverage_original"]
    enhanced = data["branch_coverage_enhanced"]
    assert isinstance(orig, (int, float)), "branch_coverage_original must be numeric"
    assert isinstance(enhanced, (int, float)), "branch_coverage_enhanced must be numeric"
    assert 0.0 < orig <= 100.0, (
        f"branch_coverage_original {orig} out of valid range (0, 100]"
    )
    assert 0.0 < enhanced <= 100.0, (
        f"branch_coverage_enhanced {enhanced} out of valid range (0, 100]"
    )
    assert enhanced >= orig, (
        f"Enhanced coverage ({enhanced}%) should be >= original ({orig}%)"
    )


# --- Subsumption DAG tests ---


def test_subsumption_dot_exists():
    """Subsumption DOT file must exist and contain valid structure."""
    assert os.path.exists(SUBSUMPTION_DOT), f"Missing {SUBSUMPTION_DOT}"
    with open(SUBSUMPTION_DOT) as f:
        content = f.read()
    assert "digraph" in content, "DOT file must contain 'digraph' keyword"
    edges = re.findall(r'"(M\d+)"\s*->\s*"(M\d+)"', content)
    assert len(edges) > 0, "DOT file must contain at least one directed edge"


def test_subsumption_png_exists():
    """Subsumption PNG must exist and be a valid PNG image."""
    assert os.path.exists(SUBSUMPTION_PNG), f"Missing {SUBSUMPTION_PNG}"
    with open(SUBSUMPTION_PNG, "rb") as f:
        header = f.read(8)
    assert header[:4] == b'\x89PNG', (
        "subsumption.png does not have valid PNG magic bytes"
    )


def test_subsumption_dag_consistency():
    """DOT edges must represent valid subsumption relationships from the kill matrix."""
    data = load_results()
    km = data["kill_matrix"]

    with open(SUBSUMPTION_DOT) as f:
        content = f.read()

    edges = re.findall(r'"(M\d+)"\s*->\s*"(M\d+)"', content)
    for src, dst in edges:
        assert src in km, f"DOT edge source {src} not in kill matrix"
        assert dst in km, f"DOT edge destination {dst} not in kill matrix"
        t_src = set(km[src])
        t_dst = set(km[dst])
        assert t_src < t_dst, (
            f"Edge {src}->{dst} invalid: T({src})={t_src} is not a proper "
            f"subset of T({dst})={t_dst}"
        )


# --- Enhanced test verification ---


def test_enhanced_tests_exist():
    """Enhanced test file must exist."""
    assert os.path.exists(ENHANCED_TESTS), f"Missing {ENHANCED_TESTS}"


def test_enhanced_tests_pass_on_original():
    """Enhanced tests must pass on the original (unmutated) code."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", ENHANCED_TESTS, "-v", "--tb=short"],
        capture_output=True, timeout=60, cwd="/app",
        env={**os.environ, "PYTHONPATH": "/app"},
    )
    assert result.returncode == 0, (
        f"Enhanced tests fail on original code:\n"
        f"{result.stdout.decode()}\n{result.stderr.decode()}"
    )


def _apply_mutation_and_check(line_num, find_text, replace_text, label):
    """Apply a mutation to mathlib.py and check if enhanced tests detect it."""
    backup = "/tmp/_mathlib_verify_backup.py"
    shutil.copy(ORIGINAL_MATHLIB, backup)
    try:
        with open(ORIGINAL_MATHLIB) as f:
            lines = f.readlines()
        assert find_text in lines[line_num - 1], (
            f"Cannot find '{find_text}' on line {line_num} for {label}"
        )
        lines[line_num - 1] = lines[line_num - 1].replace(find_text, replace_text, 1)
        with open(ORIGINAL_MATHLIB, "w") as f:
            f.writelines(lines)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", ENHANCED_TESTS, "-x", "--tb=no", "-q"],
            capture_output=True, timeout=30, cwd="/app",
            env={**os.environ, "PYTHONPATH": "/app"},
        )
        return result.returncode != 0
    finally:
        shutil.copy(backup, ORIGINAL_MATHLIB)


def test_enhanced_kills_m011():
    """Enhanced tests must detect M011: is_sorted > changed to >=."""
    caught = _apply_mutation_and_check(
        28, "arr[i] > arr[i + 1]", "arr[i] >= arr[i + 1]", "M011"
    )
    assert caught, (
        "Enhanced tests did not detect M011 (is_sorted > to >=). "
        "Need a test with duplicate elements in a sorted array."
    )


def test_enhanced_kills_m020():
    """Enhanced tests must detect M020: variance len < 2 changed to <= 2."""
    caught = _apply_mutation_and_check(
        55, "len(values) < 2", "len(values) <= 2", "M020"
    )
    assert caught, (
        "Enhanced tests did not detect M020 (variance < to <=). "
        "Need a test calling variance with exactly 2 values."
    )


def test_enhanced_kills_m033():
    """Enhanced tests must detect M033: first AND to OR in triangle inequality."""
    caught = _apply_mutation_and_check(
        87, "> c and a + c", "> c or a + c", "M033"
    )
    assert caught, (
        "Enhanced tests did not detect M033 (triangle inequality AND to OR). "
        "Need a test with sides that violate the triangle inequality."
    )


def test_enhanced_kills_m034():
    """Enhanced tests must detect M034: second AND to OR in triangle inequality."""
    caught = _apply_mutation_and_check(
        87, "> b and b + c", "> b or b + c", "M034"
    )
    assert caught, (
        "Enhanced tests did not detect M034 (triangle inequality AND to OR). "
        "Need a test with sides that violate the triangle inequality."
    )
