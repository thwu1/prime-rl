
"""
Tests for SIF parser and optimization solver.
Verifies correctness of solutions for known CUTEst problems
and tests solver generality with a new problem injected at test time.
"""

import json
import subprocess
import os
import pytest
import numpy as np


# Anti-cheat: a new SIF problem injected at test time.
# Encodes: minimize 2*x1^2 + x2^2 + x1*x2 - 7*x1 - 5*x2
#          subject to x1 + x2 <= 3, x1 >= 0, x2 >= 0
# Optimal: x* = (5/4, 7/4), f* = -73/8 = -9.125
QPTEST_SIF = """\
NAME          QPTEST

VARIABLES

    X1
    X2

GROUPS

 N  OBJ       X1        -7.0           X2        -5.0
 G  C1        X1        -1.0           X2        -1.0

CONSTANTS

    QPTEST    C1        -3.0

BOUNDS

 LO QPTEST    'DEFAULT' 0.0

START POINT

    QPTEST    X1        0.0
    QPTEST    X2        0.0

ELEMENT TYPE

 EV SQ        V1

 EV PR        V1                       V2

ELEMENT USES

 T  E1        SQ
 V  E1        V1                       X1

 T  E2        SQ
 V  E2        V1                       X2

 T  E3        PR
 V  E3        V1                       X1
 V  E3        V2                       X2

GROUP USES

 E  OBJ       E1        2.0            E2        1.0
 E  OBJ       E3        1.0

OBJECT BOUND

ENDATA

ELEMENTS      QPTEST

INDIVIDUALS

 T  SQ
 F                      V1 * V1
 G  V1                  V1 + V1
 H  V1        V1        2.0

 T  PR
 F                      V1 * V2
 G  V1                  V2
 G  V2                  V1
 H  V1        V2        1.0

ENDATA
"""


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


# ----------------------------------------------------------------
# Basic format tests
# ----------------------------------------------------------------

class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_valid_json(self):
        results = load_results()
        assert isinstance(results, dict)

    def test_all_problems_present(self):
        results = load_results()
        for name in ["ROSENBR", "HS71", "HS100"]:
            assert name in results, f"Problem {name} missing from results"

    def test_result_entries_have_required_fields(self):
        results = load_results()
        for name in ["ROSENBR", "HS71", "HS100"]:
            entry = results[name]
            assert "optimal_value" in entry, f"{name} missing optimal_value"
            assert "optimal_point" in entry, f"{name} missing optimal_point"
            assert isinstance(entry["optimal_value"], (int, float))
            assert isinstance(entry["optimal_point"], list)


# ----------------------------------------------------------------
# ROSENBR — 2-variable unconstrained (f* = 0 at (1,1))
# ----------------------------------------------------------------

class TestRosenbrock:
    def test_optimal_value(self):
        r = load_results()["ROSENBR"]
        assert abs(r["optimal_value"]) < 1e-4, (
            f"ROSENBR optimal value should be ~0, got {r['optimal_value']}"
        )

    def test_optimal_point_dimensions(self):
        x = load_results()["ROSENBR"]["optimal_point"]
        assert len(x) == 2

    def test_optimal_point_location(self):
        x = load_results()["ROSENBR"]["optimal_point"]
        assert abs(x[0] - 1.0) < 1e-2, f"x1 should be ~1.0, got {x[0]}"
        assert abs(x[1] - 1.0) < 1e-2, f"x2 should be ~1.0, got {x[1]}"


# ----------------------------------------------------------------
# HS71 — 4-variable constrained (f* ≈ 17.014, bounds [1,5])
# Constraints: x1*x2*x3*x4 >= 25, x1^2+x2^2+x3^2+x4^2 = 40
# ----------------------------------------------------------------

class TestHS71:
    def test_optimal_value(self):
        r = load_results()["HS71"]
        assert abs(r["optimal_value"] - 17.0140173) < 0.1, (
            f"HS71 optimal value should be ~17.014, got {r['optimal_value']}"
        )

    def test_optimal_point_dimensions(self):
        x = load_results()["HS71"]["optimal_point"]
        assert len(x) == 4

    def test_bounds_satisfied(self):
        x = load_results()["HS71"]["optimal_point"]
        for i, xi in enumerate(x):
            assert 1.0 - 1e-3 <= xi <= 5.0 + 1e-3, (
                f"x{i+1}={xi} violates bounds [1,5]"
            )

    def test_inequality_constraint(self):
        x = load_results()["HS71"]["optimal_point"]
        prod = x[0] * x[1] * x[2] * x[3]
        assert prod >= 25.0 - 0.1, (
            f"x1*x2*x3*x4 = {prod}, should be >= 25"
        )

    def test_equality_constraint(self):
        x = load_results()["HS71"]["optimal_point"]
        ssq = sum(xi ** 2 for xi in x)
        assert abs(ssq - 40.0) < 0.5, (
            f"sum(xi^2) = {ssq}, should be = 40"
        )


# ----------------------------------------------------------------
# HS100 — 7-variable constrained (f* ≈ 680.63, 4 inequality constraints)
# ----------------------------------------------------------------

class TestHS100:
    def test_optimal_value(self):
        r = load_results()["HS100"]
        assert abs(r["optimal_value"] - 680.6300573) < 1.0, (
            f"HS100 optimal value should be ~680.63, got {r['optimal_value']}"
        )

    def test_optimal_point_dimensions(self):
        x = load_results()["HS100"]["optimal_point"]
        assert len(x) == 7

    def test_constraint_1(self):
        x = load_results()["HS100"]["optimal_point"]
        c1 = 2 * x[0] ** 2 + 3 * x[1] ** 4 + x[2] + 4 * x[3] ** 2 + 5 * x[4]
        assert c1 <= 127.0 + 0.5, f"C1 = {c1}, should be <= 127"

    def test_constraint_2(self):
        x = load_results()["HS100"]["optimal_point"]
        c2 = 7 * x[0] + 3 * x[1] + 10 * x[2] ** 2 + x[3] - x[4]
        assert c2 <= 282.0 + 0.5, f"C2 = {c2}, should be <= 282"

    def test_constraint_3(self):
        x = load_results()["HS100"]["optimal_point"]
        c3 = 23 * x[0] + x[1] ** 2 + 6 * x[5] ** 2 - 8 * x[6]
        assert c3 <= 196.0 + 0.5, f"C3 = {c3}, should be <= 196"

    def test_constraint_4(self):
        x = load_results()["HS100"]["optimal_point"]
        c4 = (
            4 * x[0] ** 2
            + x[1] ** 2
            - 3 * x[0] * x[1]
            + 2 * x[2] ** 2
            + 5 * x[5]
            - 11 * x[6]
        )
        assert c4 <= 0.0 + 0.5, f"C4 = {c4}, should be <= 0"


# ----------------------------------------------------------------
# Solver generality — inject a new problem at test time (anti-cheat)
# ----------------------------------------------------------------

class TestSolverGenerality:
    @pytest.fixture(autouse=True, scope="class")
    def run_solver_with_qptest(self):
        """Write QPTEST.SIF and re-run the solver."""
        with open("/app/problems/QPTEST.SIF", "w") as f:
            f.write(QPTEST_SIF)
        result = subprocess.run(
            ["python3", "/app/solve.py"],
            capture_output=True,
            text=True,
            timeout=180,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Solver re-run failed:\nstdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_qptest_present(self):
        results = load_results()
        assert "QPTEST" in results, "QPTEST not in results after re-run"

    def test_qptest_optimal_value(self):
        results = load_results()
        expected = -73.0 / 8.0  # -9.125
        actual = results["QPTEST"]["optimal_value"]
        assert abs(actual - expected) < 0.1, (
            f"QPTEST optimal value should be ~{expected}, got {actual}"
        )

    def test_qptest_optimal_point(self):
        results = load_results()
        x = results["QPTEST"]["optimal_point"]
        assert len(x) == 2
        assert abs(x[0] - 5.0 / 4.0) < 0.1, f"x1 should be ~1.25, got {x[0]}"
        assert abs(x[1] - 7.0 / 4.0) < 0.1, f"x2 should be ~1.75, got {x[1]}"

    def test_qptest_constraint_satisfied(self):
        results = load_results()
        x = results["QPTEST"]["optimal_point"]
        assert x[0] + x[1] <= 3.0 + 0.01, f"x1+x2 = {x[0]+x[1]}, should be <= 3"

    def test_qptest_bounds_satisfied(self):
        results = load_results()
        x = results["QPTEST"]["optimal_point"]
        for i, xi in enumerate(x):
            assert xi >= -1e-3, f"x{i+1}={xi} violates lower bound 0"


# ----------------------------------------------------------------
# Anti-cheat: solver code must be a real implementation
# ----------------------------------------------------------------

class TestAntiCheat:
    def test_solve_py_exists(self):
        assert os.path.exists("/app/solve.py"), "solve.py not found"

    def test_solve_py_is_substantial(self):
        with open("/app/solve.py") as f:
            content = f.read()
        assert len(content) > 500, (
            "solve.py is too short to be a real SIF parser implementation"
        )

    def test_code_references_sif(self):
        # Check that the code actually deals with SIF format
        all_code = ""
        for root, _, files in os.walk("/app"):
            for fn in files:
                if fn.endswith(".py"):
                    with open(os.path.join(root, fn)) as f:
                        all_code += f.read()
        sif_indicators = ["SIF", ".SIF", "sif", "ENDATA", "ELEMENT", "GROUPS"]
        found = any(ind in all_code for ind in sif_indicators)
        assert found, "No SIF format references found in Python code"
