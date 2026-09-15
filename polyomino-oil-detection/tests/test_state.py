"""
Tests for the Oil Field Detection Pipeline.
Verifies:
  - C library builds and functions correctly
  - Solver uses ctypes to call the C library
  - Pipeline script uses make, jq, sqlite3
  - Solver correctness and cost efficiency on static and dynamic instances
  - SQLite database is correctly populated
"""

import ctypes
import json
import os
import sqlite3 as sqlite3_mod
import subprocess
import tempfile


SOLVER_PATH = "/app/solver.py"
JUDGE_PATH = "/app/judge.py"
GENERATE_PATH = "/app/generate.py"
INSTANCES_DIR = "/app/instances"
MAX_NORMALIZED_COST = 0.45
TIMEOUT_PER_INSTANCE = 120

# Attempt to build the C library at import time so solver tests can use it
_build_result = subprocess.run(
    ["make", "-C", "/app"],
    capture_output=True, text=True, timeout=60
)


def _run_solver_on_instance(instance_path):
    """Run the solver against a single instance and return the judge result."""
    result = subprocess.run(
        ["python3", JUDGE_PATH, instance_path, f"python3 {SOLVER_PATH}"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_PER_INSTANCE,
    )
    assert result.returncode == 0, (
        f"Judge exited with code {result.returncode} on {instance_path}.\n"
        f"stderr: {result.stderr[:1000]}"
    )
    stdout = result.stdout.strip()
    assert stdout, f"Judge produced no output on {instance_path}"
    output = json.loads(stdout)
    return output


# ---- Build and library tests ----

def test_build_and_library():
    """Makefile and C source exist, make succeeds, .so is loadable with correct symbols."""
    assert os.path.isfile("/app/Makefile"), (
        "Makefile not found at /app/Makefile. "
        "Create a Makefile that builds libscoring.so from scoring.c."
    )
    assert os.path.isfile("/app/scoring.c"), (
        "scoring.c not found at /app/scoring.c. "
        "Implement the scoring interface declared in /app/scoring.h."
    )
    assert _build_result.returncode == 0, (
        f"make -C /app failed with exit code {_build_result.returncode}.\n"
        f"stderr: {_build_result.stderr[:2000]}"
    )
    assert os.path.isfile("/app/libscoring.so"), (
        "libscoring.so not produced by make. "
        "Makefile must compile scoring.c into libscoring.so."
    )
    lib = ctypes.CDLL("/app/libscoring.so")
    assert hasattr(lib, "score_combo"), (
        "libscoring.so missing score_combo symbol. "
        "Implement the function declared in scoring.h."
    )
    assert hasattr(lib, "find_best_combo"), (
        "libscoring.so missing find_best_combo symbol. "
        "Implement the function declared in scoring.h."
    )


def test_scoring_function_correct():
    """C scoring function produces correct output for known inputs."""
    lib = ctypes.CDLL("/app/libscoring.so")
    lib.score_combo.restype = ctypes.c_double
    lib.score_combo.argtypes = [
        ctypes.c_int, ctypes.c_double, ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
    ]

    N = 4
    row_avg = (ctypes.c_double * 4)(1.0, 2.5, 1.5, 0.5)
    col_avg = (ctypes.c_double * 4)(0.5, 1.5, 2.0, 1.5)
    combo_rc = (ctypes.c_int * 4)(0, 2, 1, 0)
    combo_cc = (ctypes.c_int * 4)(0, 1, 1, 1)

    # Expected computation:
    # c_val = 1 - 2*0.1 = 0.8
    # sigma_sq = 4*0.1*0.9 / 3 = 0.12
    # row: -(0.36 + 0.25 + 0.09 + 0.01) = -0.71
    # col: -(0.01 + 0.09 + 0.64 + 0.09) = -0.83
    # total: -1.54 / (2*0.12) = -6.4167
    result = lib.score_combo(4, ctypes.c_double(0.1), 3,
                             row_avg, col_avg, combo_rc, combo_cc)
    expected = -6.4167
    assert abs(result - expected) < 0.01, (
        f"score_combo returned {result:.4f}, expected ~{expected:.4f}. "
        "Check the Gaussian log-likelihood formula implementation."
    )

    # Test with different inputs for robustness
    combo_rc2 = (ctypes.c_int * 4)(1, 1, 1, 0)
    combo_cc2 = (ctypes.c_int * 4)(1, 1, 1, 0)
    result2 = lib.score_combo(4, ctypes.c_double(0.1), 3,
                              row_avg, col_avg, combo_rc2, combo_cc2)
    # This should be a different score
    assert result2 != result, "score_combo should return different scores for different inputs"


# ---- Solver structure tests ----

def test_solver_uses_c_library():
    """Solver must use ctypes to load and call the C scoring library."""
    assert os.path.isfile(SOLVER_PATH), (
        f"Solver not found at {SOLVER_PATH}. "
        "Create a Python solver that uses ctypes to call libscoring.so."
    )
    with open(SOLVER_PATH) as f:
        code = f.read()
    assert "ctypes" in code, (
        "solver.py does not reference ctypes. "
        "The solver must load libscoring.so via Python's ctypes module."
    )
    assert "libscoring" in code or "scoring" in code, (
        "solver.py does not reference the scoring library. "
        "The solver must load and call libscoring.so for beam search scoring."
    )


def test_pipeline_uses_tools():
    """Pipeline script must exist and use make, jq, and sqlite3."""
    assert os.path.isfile("/app/pipeline.sh"), (
        "pipeline.sh not found at /app/pipeline.sh. "
        "Create a pipeline script that orchestrates the build and run process."
    )
    with open("/app/pipeline.sh") as f:
        code = f.read()
    assert "jq" in code, (
        "pipeline.sh does not use jq. "
        "Use jq to extract fields from judge JSON output."
    )
    assert "sqlite3" in code, (
        "pipeline.sh does not use sqlite3. "
        "Use sqlite3 to store results in /app/results.db."
    )
    assert "make" in code, (
        "pipeline.sh does not use make. "
        "Use make to build the C scoring library."
    )


# ---- Solver correctness tests ----

def test_solver_solves_all_static_instances():
    """Solver must correctly identify all oil cells on every pre-generated instance."""
    instance_files = sorted(
        os.path.join(INSTANCES_DIR, f)
        for f in os.listdir(INSTANCES_DIR)
        if f.endswith(".json")
    )
    assert len(instance_files) == 5, f"Expected 5 instance files, found {len(instance_files)}"

    results = []
    for inst_path in instance_files:
        output = _run_solver_on_instance(inst_path)
        assert output["solved"], (
            f"Solver failed to correctly identify oil cells on {inst_path}. "
            f"Cost so far: {output['cost']}, ops: {output['ops']}"
        )
        results.append(output)

    # Check average normalized cost
    avg_norm_cost = sum(r["normalized_cost"] for r in results) / len(results)
    assert avg_norm_cost <= MAX_NORMALIZED_COST, (
        f"Average normalized cost {avg_norm_cost:.4f} exceeds threshold {MAX_NORMALIZED_COST}. "
        f"Per-instance costs: {[r['normalized_cost'] for r in results]}"
    )


def test_solver_solves_dynamic_instance():
    """Solver must also solve a freshly generated instance (anti-cheat)."""
    gen_result = subprocess.run(
        ["python3", GENERATE_PATH, "77777", "10", "3", "0.15"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert gen_result.returncode == 0, f"Generator failed: {gen_result.stderr}"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    ) as f:
        f.write(gen_result.stdout)
        tmp_path = f.name

    try:
        output = _run_solver_on_instance(tmp_path)
        assert output["solved"], (
            f"Solver failed on dynamically generated instance (seed=77777). "
            f"Cost: {output['cost']}, ops: {output['ops']}"
        )
        assert output["normalized_cost"] <= MAX_NORMALIZED_COST, (
            f"Normalized cost {output['normalized_cost']:.4f} on dynamic instance "
            f"exceeds threshold {MAX_NORMALIZED_COST}"
        )
    finally:
        os.unlink(tmp_path)


# ---- SQLite database test ----

def test_sqlite_database():
    """Results database must exist with correct schema and data."""
    db_path = "/app/results.db"
    assert os.path.isfile(db_path), (
        f"SQLite database not found at {db_path}. "
        "Run pipeline.sh to populate results.db."
    )

    conn = sqlite3_mod.connect(db_path)
    cursor = conn.cursor()

    # Check table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='results'"
    )
    row = cursor.fetchone()
    assert row is not None, (
        "'results' table not found in results.db. "
        "Pipeline must create this table with the schema from PROBLEM.md."
    )

    # Check required columns exist
    cursor.execute("PRAGMA table_info(results)")
    columns = {r[1] for r in cursor.fetchall()}
    required = {
        "instance_name", "grid_size", "num_fields", "epsilon",
        "solved", "cost", "normalized_cost"
    }
    missing = required - columns
    assert not missing, (
        f"Missing columns in results table: {missing}. "
        "Schema must match the specification in PROBLEM.md."
    )

    # Check data completeness
    cursor.execute("SELECT COUNT(*) FROM results")
    count = cursor.fetchone()[0]
    assert count >= 5, (
        f"Expected at least 5 rows in results table, found {count}. "
        "Pipeline must run solver on all instances."
    )

    # Check all instances were solved
    cursor.execute("SELECT COUNT(*) FROM results WHERE solved=1")
    solved_count = cursor.fetchone()[0]
    assert solved_count >= 5, (
        f"Only {solved_count} instances marked as solved. All 5 must be solved."
    )

    # Check average cost
    cursor.execute("SELECT AVG(normalized_cost) FROM results WHERE solved=1")
    avg_cost = cursor.fetchone()[0]
    assert avg_cost is not None, "No solved instances found in database"
    assert avg_cost <= MAX_NORMALIZED_COST, (
        f"Average normalized cost in database is {avg_cost:.4f}, "
        f"exceeds threshold {MAX_NORMALIZED_COST}."
    )

    conn.close()
