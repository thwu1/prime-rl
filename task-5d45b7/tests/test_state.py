
"""Tests for SIF parser and solver task."""
import json
import os
import math


# --- Reference objective functions for independent re-evaluation ---

def rosenbrock(x):
    """100*(x2 - x1^2)^2 + (x1 - 1)^2"""
    return 100.0 * (x[1] - x[0] ** 2) ** 2 + (x[0] - 1.0) ** 2


def hs71_obj(x):
    """x1*x4*(x1 + x2 + x3) + x3"""
    return x[0] * x[3] * (x[0] + x[1] + x[2]) + x[2]


def hs71_con1(x):
    """x1*x2*x3*x4 (must be >= 25)"""
    return x[0] * x[1] * x[2] * x[3]


def hs71_con2(x):
    """x1^2 + x2^2 + x3^2 + x4^2 (must == 40)"""
    return sum(xi ** 2 for xi in x)


def benchopt_obj(x):
    """(x1-1)^2 + 4*(x2-2)^2 + 3*x1*x2"""
    return (x[0] - 1.0) ** 2 + 4.0 * (x[1] - 2.0) ** 2 + 3.0 * x[0] * x[1]


def benchopt_con1(x):
    """x1 + x2 (must be >= 2)"""
    return x[0] + x[1]


# --- Test classes ---

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"

    def test_results_valid_json(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        assert "problems" in data
        assert isinstance(data["problems"], list)
        assert len(data["problems"]) == 3


class TestAllProblemsPresent:
    def setup_method(self):
        with open("/app/results.json") as f:
            self.data = json.load(f)
        self.by_name = {r["name"]: r for r in self.data["problems"]}

    def test_rosenbr_present(self):
        assert "ROSENBR" in self.by_name

    def test_hs71_present(self):
        assert "HS71" in self.by_name

    def test_benchopt_present(self):
        assert "BENCHOPT" in self.by_name


class TestVariableCounts:
    def setup_method(self):
        with open("/app/results.json") as f:
            self.data = json.load(f)
        self.by_name = {r["name"]: r for r in self.data["problems"]}

    def test_rosenbr_n_vars(self):
        assert self.by_name["ROSENBR"]["n_vars"] == 2

    def test_hs71_n_vars(self):
        assert self.by_name["HS71"]["n_vars"] == 4

    def test_benchopt_n_vars(self):
        assert self.by_name["BENCHOPT"]["n_vars"] == 2


class TestConstraintCounts:
    def setup_method(self):
        with open("/app/results.json") as f:
            self.data = json.load(f)
        self.by_name = {r["name"]: r for r in self.data["problems"]}

    def test_rosenbr_n_constraints(self):
        assert self.by_name["ROSENBR"]["n_constraints"] == 0

    def test_hs71_n_constraints(self):
        assert self.by_name["HS71"]["n_constraints"] == 2

    def test_benchopt_n_constraints(self):
        assert self.by_name["BENCHOPT"]["n_constraints"] == 1


class TestRosenbrSolution:
    def setup_method(self):
        with open("/app/results.json") as f:
            self.data = json.load(f)
        self.r = {r["name"]: r for r in self.data["problems"]}["ROSENBR"]

    def test_optimal_value(self):
        assert abs(self.r["optimal_value"] - 0.0) < 1e-4, \
            f"ROSENBR optimal {self.r['optimal_value']} != 0.0"

    def test_solution_length(self):
        assert len(self.r["solution"]) == 2

    def test_solution_evaluates_correctly(self):
        x = self.r["solution"]
        fval = rosenbrock(x)
        assert abs(fval - self.r["optimal_value"]) < 1e-6, \
            f"Re-evaluation {fval} != reported {self.r['optimal_value']}"

    def test_solution_at_known_minimum(self):
        x = self.r["solution"]
        assert abs(x[0] - 1.0) < 1e-3, f"x1={x[0]} not near 1.0"
        assert abs(x[1] - 1.0) < 1e-3, f"x2={x[1]} not near 1.0"


class TestHS71Solution:
    def setup_method(self):
        with open("/app/results.json") as f:
            self.data = json.load(f)
        self.r = {r["name"]: r for r in self.data["problems"]}["HS71"]

    def test_optimal_value(self):
        assert abs(self.r["optimal_value"] - 17.0140173) < 1e-2, \
            f"HS71 optimal {self.r['optimal_value']} not near 17.014"

    def test_solution_length(self):
        assert len(self.r["solution"]) == 4

    def test_solution_evaluates_correctly(self):
        x = self.r["solution"]
        fval = hs71_obj(x)
        assert abs(fval - self.r["optimal_value"]) < 1e-3, \
            f"Re-evaluation {fval} != reported {self.r['optimal_value']}"

    def test_constraint_product_ge_25(self):
        x = self.r["solution"]
        c1 = hs71_con1(x)
        assert c1 >= 25.0 - 1e-3, f"Product constraint violated: {c1} < 25"

    def test_constraint_sumsq_eq_40(self):
        x = self.r["solution"]
        c2 = hs71_con2(x)
        assert abs(c2 - 40.0) < 1e-2, f"Sum-of-squares constraint violated: {c2} != 40"

    def test_bounds_satisfied(self):
        x = self.r["solution"]
        for i, xi in enumerate(x):
            assert 1.0 - 1e-6 <= xi <= 5.0 + 1e-6, \
                f"x[{i}]={xi} out of bounds [1, 5]"


class TestBenchoptSolution:
    """Tests for the custom BENCHOPT problem (not in any public CUTEst set)."""

    def setup_method(self):
        with open("/app/results.json") as f:
            self.data = json.load(f)
        self.r = {r["name"]: r for r in self.data["problems"]}["BENCHOPT"]

    def test_optimal_value(self):
        assert abs(self.r["optimal_value"] - (-1.0)) < 1e-4, \
            f"BENCHOPT optimal {self.r['optimal_value']} not near -1.0"

    def test_solution_length(self):
        assert len(self.r["solution"]) == 2

    def test_solution_evaluates_correctly(self):
        x = self.r["solution"]
        fval = benchopt_obj(x)
        assert abs(fval - self.r["optimal_value"]) < 1e-4, \
            f"Re-evaluation {fval} != reported {self.r['optimal_value']}"

    def test_constraint_satisfied(self):
        x = self.r["solution"]
        cval = benchopt_con1(x)
        assert cval >= 2.0 - 1e-4, f"Constraint violated: x1+x2={cval} < 2"

    def test_bounds_satisfied(self):
        x = self.r["solution"]
        for i, xi in enumerate(x):
            assert -10.0 - 1e-6 <= xi <= 10.0 + 1e-6, \
                f"x[{i}]={xi} out of bounds [-10, 10]"

    def test_solution_near_known(self):
        x = self.r["solution"]
        assert abs(x[0] - (-1.0)) < 1e-2, f"x1={x[0]} not near -1.0"
        assert abs(x[1] - 3.0) < 1e-2, f"x2={x[1]} not near 3.0"


class TestAntiCheat:
    def test_parser_module_exists(self):
        """Verify a Python file with SIF parsing logic exists in /app."""
        found = False
        for root, dirs, files in os.walk("/app"):
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    try:
                        with open(path) as fh:
                            content = fh.read()
                        if ("ELEMENT" in content and "GROUP" in content
                                and "VARIABLES" in content):
                            found = True
                            break
                    except Exception:
                        continue
            if found:
                break
        assert found, "No SIF parser module found in /app"
