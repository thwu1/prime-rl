
"""
Tests for the XCSP3-to-MiniZinc compiler.
Verifies that MiniZinc models are generated and solutions are correct.
"""

import json
import os
import subprocess
import pytest

RESULTS_DIR = "/app/results"
MODELS_DIR = "/app/models"


@pytest.fixture(scope="session", autouse=True)
def run_compiler():
    """Run the XCSP3-to-MiniZinc compiler before all tests."""
    assert os.path.exists("/app/compiler.py"), "Compiler not found at /app/compiler.py"
    result = subprocess.run(
        ["python3", "/app/compiler.py"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/app",
    )
    assert result.returncode == 0, f"Compiler failed with stderr:\n{result.stderr}"


def load_result(name):
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    assert os.path.exists(path), f"Result file {path} not found"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# MiniZinc model verification: prove actual XCSP3-to-MiniZinc translation
# ---------------------------------------------------------------------------

class TestMiniZincModels:
    """Verify MiniZinc model files are generated with correct structure."""

    INSTANCES = [
        "magic_square", "queens", "knapsack",
        "scheduling", "all_interval", "unsat", "coloring",
    ]

    @pytest.mark.parametrize("name", INSTANCES)
    def test_model_file_exists(self, name):
        path = os.path.join(MODELS_DIR, f"{name}.mzn")
        assert os.path.exists(path), f"MiniZinc model {path} not found"

    @pytest.mark.parametrize("name", INSTANCES)
    def test_model_has_solve_statement(self, name):
        path = os.path.join(MODELS_DIR, f"{name}.mzn")
        with open(path) as f:
            content = f.read()
        assert "solve " in content, f"Model {name}.mzn missing solve statement"

    def test_magic_square_model_uses_alldifferent(self):
        with open(os.path.join(MODELS_DIR, "magic_square.mzn")) as f:
            content = f.read()
        assert "alldifferent" in content, \
            "magic_square.mzn must translate allDifferent to MiniZinc alldifferent"

    def test_scheduling_model_uses_table(self):
        with open(os.path.join(MODELS_DIR, "scheduling.mzn")) as f:
            content = f.read()
        assert "table" in content, \
            "scheduling.mzn must translate extension/supports to MiniZinc table constraint"

    def test_queens_model_uses_abs(self):
        with open(os.path.join(MODELS_DIR, "queens.mzn")) as f:
            content = f.read()
        assert "abs" in content, \
            "queens.mzn must translate dist() to abs() in MiniZinc"

    def test_knapsack_model_uses_maximize(self):
        with open(os.path.join(MODELS_DIR, "knapsack.mzn")) as f:
            content = f.read()
        assert "maximize" in content, \
            "knapsack.mzn must translate <maximize> to solve maximize"

    def test_all_interval_model_has_two_arrays(self):
        with open(os.path.join(MODELS_DIR, "all_interval.mzn")) as f:
            content = f.read()
        assert "var" in content and ": x;" in content, \
            "all_interval.mzn must declare array x"
        assert ": y;" in content, \
            "all_interval.mzn must declare array y"


# ---------------------------------------------------------------------------
# Magic Square: 3x3, values 1-9 all different, rows/cols/diags = 15
# ---------------------------------------------------------------------------

class TestMagicSquare:

    def test_status_is_sat(self):
        result = load_result("magic_square")
        assert result["status"] == "SAT"

    def test_has_nine_variables(self):
        result = load_result("magic_square")
        sol = result["solution"]
        for i in range(9):
            assert f"x[{i}]" in sol, f"Missing variable x[{i}]"

    def test_values_in_domain(self):
        result = load_result("magic_square")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(9)]
        assert all(1 <= v <= 9 for v in x), f"Values out of range: {x}"

    def test_all_different(self):
        result = load_result("magic_square")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(9)]
        assert len(set(x)) == 9, f"Values not all different: {x}"

    def test_row_sums(self):
        result = load_result("magic_square")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(9)]
        for r in range(3):
            s = sum(x[r * 3:(r + 1) * 3])
            assert s == 15, f"Row {r} sum={s}, expected 15"

    def test_column_sums(self):
        result = load_result("magic_square")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(9)]
        for c in range(3):
            s = x[c] + x[c + 3] + x[c + 6]
            assert s == 15, f"Col {c} sum={s}, expected 15"

    def test_diagonal_sums(self):
        result = load_result("magic_square")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(9)]
        assert x[0] + x[4] + x[8] == 15, f"Main diag sum={x[0]+x[4]+x[8]}"
        assert x[2] + x[4] + x[6] == 15, f"Anti diag sum={x[2]+x[4]+x[6]}"


# ---------------------------------------------------------------------------
# 8-Queens: 8 non-attacking queens
# ---------------------------------------------------------------------------

class TestQueens:

    def test_status_is_sat(self):
        result = load_result("queens")
        assert result["status"] == "SAT"

    def test_values_in_domain(self):
        result = load_result("queens")
        sol = result["solution"]
        q = [sol[f"q[{i}]"] for i in range(8)]
        assert all(0 <= v <= 7 for v in q), f"Values out of range: {q}"

    def test_all_different_rows(self):
        result = load_result("queens")
        sol = result["solution"]
        q = [sol[f"q[{i}]"] for i in range(8)]
        assert len(set(q)) == 8, f"Queens share rows: {q}"

    def test_no_diagonal_attacks(self):
        result = load_result("queens")
        sol = result["solution"]
        q = [sol[f"q[{i}]"] for i in range(8)]
        for i in range(8):
            for j in range(i + 1, 8):
                assert abs(q[i] - q[j]) != (j - i), (
                    f"Queens at cols {i},{j} (rows {q[i]},{q[j]}) attack diagonally"
                )


# ---------------------------------------------------------------------------
# Knapsack: 0-1 knapsack, optimal = 172
# ---------------------------------------------------------------------------

class TestKnapsack:

    def test_status_is_optimum(self):
        result = load_result("knapsack")
        assert result["status"] == "OPTIMUM"

    def test_values_are_binary(self):
        result = load_result("knapsack")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(5)]
        assert all(v in (0, 1) for v in x), f"Non-binary values: {x}"

    def test_weight_constraint(self):
        result = load_result("knapsack")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(5)]
        weights = [11, 24, 5, 23, 16]
        total_weight = sum(w * v for w, v in zip(weights, x))
        assert total_weight <= 40, f"Weight {total_weight} exceeds capacity 40"

    def test_objective_matches_solution(self):
        result = load_result("knapsack")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(5)]
        values = [46, 46, 38, 88, 3]
        computed = sum(c * v for c, v in zip(values, x))
        assert computed == result["objective"], (
            f"Reported objective {result['objective']} != computed {computed}"
        )

    def test_optimal_value(self):
        result = load_result("knapsack")
        assert result["objective"] == 172, (
            f"Optimal value should be 172, got {result['objective']}"
        )


# ---------------------------------------------------------------------------
# Scheduling: 5 tasks, allDifferent + precedence via extension/table
# ---------------------------------------------------------------------------

class TestScheduling:
    # Precedence DAG: 0->1, 0->2, 1->3, 2->3, 3->4
    PRECEDENCES = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4)]

    def test_status_is_sat(self):
        result = load_result("scheduling")
        assert result["status"] == "SAT"

    def test_has_five_variables(self):
        result = load_result("scheduling")
        sol = result["solution"]
        for i in range(5):
            assert f"s[{i}]" in sol, f"Missing variable s[{i}]"

    def test_values_in_domain(self):
        result = load_result("scheduling")
        sol = result["solution"]
        s = [sol[f"s[{i}]"] for i in range(5)]
        assert all(0 <= v <= 4 for v in s), f"Values out of range: {s}"

    def test_all_different(self):
        result = load_result("scheduling")
        sol = result["solution"]
        s = [sol[f"s[{i}]"] for i in range(5)]
        assert len(set(s)) == 5, f"Values not all different: {s}"

    def test_precedence_constraints(self):
        result = load_result("scheduling")
        sol = result["solution"]
        s = [sol[f"s[{i}]"] for i in range(5)]
        for i, j in self.PRECEDENCES:
            assert s[i] < s[j], (
                f"Precedence violated: s[{i}]={s[i]} not < s[{j}]={s[j]}"
            )


# ---------------------------------------------------------------------------
# All-Interval Series: two arrays, group templates, dist()
# ---------------------------------------------------------------------------

class TestAllInterval:

    def test_status_is_sat(self):
        result = load_result("all_interval")
        assert result["status"] == "SAT"

    def test_x_values_in_domain(self):
        result = load_result("all_interval")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(5)]
        assert all(0 <= v <= 4 for v in x), f"x values out of range: {x}"

    def test_y_values_in_domain(self):
        result = load_result("all_interval")
        sol = result["solution"]
        y = [sol[f"y[{i}]"] for i in range(4)]
        assert all(1 <= v <= 4 for v in y), f"y values out of range: {y}"

    def test_x_all_different(self):
        result = load_result("all_interval")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(5)]
        assert len(set(x)) == 5, f"x values not all different: {x}"

    def test_y_all_different(self):
        result = load_result("all_interval")
        sol = result["solution"]
        y = [sol[f"y[{i}]"] for i in range(4)]
        assert len(set(y)) == 4, f"y values not all different: {y}"

    def test_channeling_constraints(self):
        result = load_result("all_interval")
        sol = result["solution"]
        x = [sol[f"x[{i}]"] for i in range(5)]
        y = [sol[f"y[{i}]"] for i in range(4)]
        for i in range(4):
            expected = abs(x[i] - x[i + 1])
            assert y[i] == expected, (
                f"y[{i}]={y[i]} != |x[{i}]-x[{i+1}]| = |{x[i]}-{x[i+1]}| = {expected}"
            )


# ---------------------------------------------------------------------------
# UNSAT: pigeonhole (3 vars, domain {1,2}, allDifferent)
# ---------------------------------------------------------------------------

class TestUnsat:

    def test_status_is_unsat(self):
        result = load_result("unsat")
        assert result["status"] == "UNSAT"

    def test_no_solution_provided(self):
        result = load_result("unsat")
        assert result.get("solution") is None or "solution" not in result


# ---------------------------------------------------------------------------
# Graph Coloring: 6 nodes, 3 colors, 8 adjacency constraints
# ---------------------------------------------------------------------------

class TestColoring:
    # Graph edges derived from the coloring instance
    EDGES = [(0, 1), (0, 2), (1, 2), (1, 3), (2, 4), (3, 4), (3, 5), (4, 5)]

    def test_status_is_sat(self):
        result = load_result("coloring")
        assert result["status"] == "SAT"

    def test_has_six_variables(self):
        result = load_result("coloring")
        sol = result["solution"]
        for i in range(6):
            assert f"c[{i}]" in sol, f"Missing variable c[{i}]"

    def test_values_in_domain(self):
        result = load_result("coloring")
        sol = result["solution"]
        c = [sol[f"c[{i}]"] for i in range(6)]
        assert all(0 <= v <= 2 for v in c), f"Values out of range: {c}"

    def test_adjacency_constraints(self):
        result = load_result("coloring")
        sol = result["solution"]
        c = [sol[f"c[{i}]"] for i in range(6)]
        for i, j in self.EDGES:
            assert c[i] != c[j], (
                f"Adjacent nodes c[{i}]={c[i]} and c[{j}]={c[j]} share the same color"
            )
