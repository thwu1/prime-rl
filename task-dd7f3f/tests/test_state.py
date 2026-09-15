
"""Tests for One-Sided Crossing Minimization dual SAT/ILP solver pipeline."""

import os
import re
import json
import subprocess
import pytest

INSTANCES_DIR = "/app/instances"
OUTPUT_DIR = "/app/output"
SAT_DIR = "/app/sat"
ILP_DIR = "/app/ilp"
REPORT_PATH = "/app/report.json"

# Optimal crossing numbers independently verified via brute-force (n1<=8)
# and bitmask DP cross-validated against ILP/glpsol (n1>8).
OPTIMAL_CROSSINGS = {
    "instance_01": 1,
    "instance_02": 2,
    "instance_03": 13,
    "instance_04": 39,
    "instance_05": 55,
    "instance_06": 85,
    "instance_07": 105,
}

INSTANCE_NAMES = sorted(OPTIMAL_CROSSINGS.keys())


def parse_instance(filepath):
    """Parse a .gr instance file. Returns (n0, n1, edges)."""
    n0 = n1 = 0
    edges = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                n0, n1 = int(parts[2]), int(parts[3])
            else:
                parts = line.split()
                edges.append((int(parts[0]), int(parts[1])))
    return n0, n1, edges


def count_crossings(edges, order):
    """Count edge crossings for a given B-vertex ordering."""
    pos = {v: i for i, v in enumerate(order)}
    c = 0
    for i in range(len(edges)):
        a1, b1 = edges[i]
        for j in range(i + 1, len(edges)):
            a2, b2 = edges[j]
            if a1 == a2 or b1 == b2:
                continue
            if (a1 < a2 and pos[b1] > pos[b2]) or (a1 > a2 and pos[b1] < pos[b2]):
                c += 1
    return c


# ============================================================
# Core solution correctness
# ============================================================

@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_solution_exists(name):
    """Solution file must exist for each instance."""
    assert os.path.isfile(os.path.join(OUTPUT_DIR, f"{name}.sol")), \
        f"Solution file /app/output/{name}.sol missing"


@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_valid_permutation(name):
    """Solution must be a valid permutation of B-vertices."""
    sol_path = os.path.join(OUTPUT_DIR, f"{name}.sol")
    if not os.path.isfile(sol_path):
        pytest.skip("Solution file missing")

    n0, n1, edges = parse_instance(os.path.join(INSTANCES_DIR, f"{name}.gr"))
    with open(sol_path) as f:
        order = [int(l.strip()) for l in f if l.strip() and not l.startswith("c")]

    expected = set(range(n0 + 1, n0 + n1 + 1))
    assert len(order) == n1, f"Expected {n1} vertices, got {len(order)}"
    assert set(order) == expected, "Output is not a valid permutation of B-vertices"


@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_optimal_crossings(name):
    """Solution must achieve the minimum (optimal) crossing number."""
    sol_path = os.path.join(OUTPUT_DIR, f"{name}.sol")
    if not os.path.isfile(sol_path):
        pytest.skip("Solution file missing")

    n0, n1, edges = parse_instance(os.path.join(INSTANCES_DIR, f"{name}.gr"))
    with open(sol_path) as f:
        order = [int(l.strip()) for l in f if l.strip() and not l.startswith("c")]

    if len(order) != n1 or set(order) != set(range(n0 + 1, n0 + n1 + 1)):
        pytest.skip("Invalid permutation; see test_valid_permutation")

    actual = count_crossings(edges, order)
    assert actual == OPTIMAL_CROSSINGS[name], \
        f"{name}: crossing count {actual} != optimal {OPTIMAL_CROSSINGS[name]}"


def test_solver_executable_exists():
    """The solver executable must exist at /app/solver."""
    assert os.path.isfile("/app/solver"), "Solver executable not found at /app/solver"
    assert os.access("/app/solver", os.X_OK), "/app/solver exists but is not executable"


# ============================================================
# SAT encoding artifact verification
# ============================================================

@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_sat_cnf_exists(name):
    """DIMACS CNF file must exist for each instance."""
    assert os.path.isfile(os.path.join(SAT_DIR, f"{name}.cnf")), \
        f"DIMACS CNF file /app/sat/{name}.cnf missing"


@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_sat_cnf_valid_dimacs(name):
    """CNF file must conform to DIMACS format with valid header and clauses."""
    cnf_path = os.path.join(SAT_DIR, f"{name}.cnf")
    if not os.path.isfile(cnf_path):
        pytest.skip("CNF file missing")

    with open(cnf_path) as f:
        lines = f.readlines()

    header_found = False
    num_vars = num_clauses = 0
    clause_count = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            assert parts[1] == "cnf", f"Expected 'cnf' descriptor, got '{parts[1]}'"
            num_vars = int(parts[2])
            num_clauses = int(parts[3])
            header_found = True
            assert num_vars > 0, "Number of variables must be positive"
            assert num_clauses > 0, "Number of clauses must be positive"
        else:
            tokens = line.split()
            assert tokens[-1] == "0", f"Clause must terminate with 0"
            for tok in tokens[:-1]:
                lit = int(tok)
                assert lit != 0, "Non-terminal literal cannot be 0"
                assert abs(lit) <= num_vars, \
                    f"Variable index {abs(lit)} exceeds declared count {num_vars}"
            clause_count += 1

    assert header_found, "Missing 'p cnf' header line"
    assert clause_count == num_clauses, \
        f"Header declares {num_clauses} clauses but file contains {clause_count}"


@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_sat_cnf_satisfiable(name):
    """Running minisat on the CNF must return SAT (optimal bound is achievable)."""
    cnf_path = os.path.join(SAT_DIR, f"{name}.cnf")
    if not os.path.isfile(cnf_path):
        pytest.skip("CNF file missing")

    sol_path = os.path.join(SAT_DIR, f"{name}_verify.sol")
    try:
        subprocess.run(
            ["minisat", cnf_path, sol_path],
            capture_output=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"minisat timed out on {name}.cnf")

    assert os.path.isfile(sol_path), "minisat produced no output file"
    with open(sol_path) as f:
        status = f.readline().strip()
    assert status == "SAT", \
        f"CNF for {name} is UNSAT — the encoding must admit the optimal solution"


# ============================================================
# ILP model artifact verification
# ============================================================

@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_ilp_lp_exists(name):
    """GLPK LP-format model file must exist for each instance."""
    assert os.path.isfile(os.path.join(ILP_DIR, f"{name}.lp")), \
        f"LP model file /app/ilp/{name}.lp missing"


@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_ilp_lp_valid_structure(name):
    """LP file must have the mandatory sections of CPLEX LP format."""
    lp_path = os.path.join(ILP_DIR, f"{name}.lp")
    if not os.path.isfile(lp_path):
        pytest.skip("LP file missing")

    with open(lp_path) as f:
        content = f.read()

    cl = content.lower()
    assert "minimize" in cl or "maximize" in cl, \
        "LP file must contain a 'Minimize' or 'Maximize' section"
    assert "subject to" in cl, \
        "LP file must contain a 'Subject To' section"
    assert "end" in cl, \
        "LP file must terminate with 'End'"
    assert "binaries" in cl or "binary" in cl or "generals" in cl, \
        "LP file must declare integer or binary variables"


@pytest.mark.parametrize("name", INSTANCE_NAMES)
def test_ilp_optimal_objective(name):
    """glpsol must solve the LP model to integer optimality with correct objective."""
    lp_path = os.path.join(ILP_DIR, f"{name}.lp")
    if not os.path.isfile(lp_path):
        pytest.skip("LP file missing")

    sol_path = os.path.join(ILP_DIR, f"{name}_verify.txt")
    try:
        result = subprocess.run(
            ["glpsol", "--lp", lp_path, "-o", sol_path],
            capture_output=True, text=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"glpsol timed out on {name}.lp")

    assert result.returncode == 0, \
        f"glpsol failed on {name}.lp: {result.stderr[:300]}"

    # Parse objective from solution file and stdout combined
    file_content = ""
    if os.path.isfile(sol_path):
        with open(sol_path) as f:
            file_content = f.read()

    combined = file_content + "\n" + result.stdout
    obj_match = re.search(r"obj\s*=\s*([\d.eE+\-]+)", combined)
    assert obj_match, "Could not parse objective value from GLPK output"
    obj_val = float(obj_match.group(1))
    expected = OPTIMAL_CROSSINGS[name]
    assert abs(obj_val - expected) < 0.5, \
        f"{name}: GLPK objective {obj_val} != expected optimal {expected}"


# ============================================================
# Cross-validation report
# ============================================================

def test_report_exists():
    """Cross-validation report must exist."""
    assert os.path.isfile(REPORT_PATH), "/app/report.json missing"


def test_report_agreement():
    """SAT and ILP crossing counts must agree and match optimal for every instance."""
    if not os.path.isfile(REPORT_PATH):
        pytest.skip("report.json missing")

    with open(REPORT_PATH) as f:
        report = json.load(f)

    for name in INSTANCE_NAMES:
        assert name in report, f"{name} missing from report.json"
        entry = report[name]
        assert "sat_crossings" in entry and "ilp_crossings" in entry, \
            f"{name}: report must contain sat_crossings and ilp_crossings"
        assert entry["sat_crossings"] == entry["ilp_crossings"], \
            f"{name}: SAT ({entry['sat_crossings']}) != ILP ({entry['ilp_crossings']})"
        assert entry["sat_crossings"] == OPTIMAL_CROSSINGS[name], \
            f"{name}: reported crossings {entry['sat_crossings']} != optimal {OPTIMAL_CROSSINGS[name]}"
