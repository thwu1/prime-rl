
import json
import math
import os

import pytest

# Instance parameters — must match /app/data/ files exactly
ROLL_WIDTH = 1000
ORDERS = [
    {"width": 141, "demand": 97},
    {"width": 168, "demand": 48},
    {"width": 193, "demand": 132},
    {"width": 207, "demand": 78},
    {"width": 248, "demand": 59},
    {"width": 271, "demand": 105},
    {"width": 314, "demand": 43},
    {"width": 337, "demand": 67},
    {"width": 379, "demand": 34},
    {"width": 413, "demand": 52},
]

WIDTHS = [o["width"] for o in ORDERS]
DEMANDS = [o["demand"] for o in ORDERS]
N = len(ORDERS)

# Total demanded material area
TOTAL_AREA = sum(w * d for w, d in zip(WIDTHS, DEMANDS))  # 176893

# Trivial lower bound: total area / roll width
TRIVIAL_LB = TOTAL_AREA / ROLL_WIDTH  # 176.893

# Basic upper bound: each width in its own pattern, integer quantities
BASIC_UB = sum(
    math.ceil(d / (ROLL_WIDTH // w)) for w, d in zip(WIDTHS, DEMANDS)
)  # 213


@pytest.fixture
def solution():
    path = "/app/results/solution.json"
    assert os.path.isfile(path), f"Solution file not found at {path}"
    with open(path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON in solution file: {e}")
    return data


class TestFileStructure:
    def test_solution_file_exists(self):
        assert os.path.isfile("/app/results/solution.json"), (
            "Solution file /app/results/solution.json not found"
        )

    def test_required_fields(self, solution):
        required = [
            "lower_bound",
            "integer_objective",
            "patterns",
            "total_waste",
            "num_distinct_patterns",
            "optimization_iterations",
        ]
        for field in required:
            assert field in solution, f"Missing required field: {field}"

    def test_lower_bound_is_numeric(self, solution):
        assert isinstance(solution["lower_bound"], (int, float)), (
            f"lower_bound should be numeric, got {type(solution['lower_bound'])}"
        )

    def test_integer_objective_is_int(self, solution):
        assert isinstance(solution["integer_objective"], int), (
            f"integer_objective should be int, got {type(solution['integer_objective'])}"
        )

    def test_patterns_is_list(self, solution):
        assert isinstance(solution["patterns"], list), "patterns should be a list"
        assert len(solution["patterns"]) > 0, "patterns list should not be empty"


class TestBoundsConsistency:
    def test_lower_bound_above_trivial(self, solution):
        lb = solution["lower_bound"]
        assert lb >= TRIVIAL_LB - 0.1, (
            f"Lower bound {lb:.4f} is below the trivial area bound "
            f"{TRIVIAL_LB:.4f}"
        )

    def test_integer_above_trivial(self, solution):
        obj = solution["integer_objective"]
        assert obj >= math.ceil(TRIVIAL_LB), (
            f"Integer objective {obj} below trivial lower bound "
            f"{math.ceil(TRIVIAL_LB)}"
        )

    def test_integer_below_basic_ub(self, solution):
        obj = solution["integer_objective"]
        assert obj <= BASIC_UB + 5, (
            f"Integer objective {obj} exceeds basic upper bound {BASIC_UB} + "
            f"tolerance"
        )

    def test_lower_bound_leq_integer(self, solution):
        assert solution["lower_bound"] <= solution["integer_objective"] + 0.01, (
            f"Lower bound {solution['lower_bound']:.4f} should not exceed "
            f"integer objective {solution['integer_objective']}"
        )

    def test_integrality_gap_reasonable(self, solution):
        gap = solution["integer_objective"] - solution["lower_bound"]
        assert gap <= 15, (
            f"Integrality gap {gap:.4f} is unreasonably large for this "
            f"instance"
        )

    def test_solution_better_than_basic(self, solution):
        """Solution must be strictly below the naive single-item-type upper
        bound."""
        assert solution["integer_objective"] < BASIC_UB, (
            f"Integer solution {solution['integer_objective']} is not better "
            f"than basic single-pattern upper bound {BASIC_UB}"
        )


class TestPatternValidity:
    def test_every_pattern_fits_roll(self, solution):
        valid_widths = {str(w) for w in WIDTHS}
        for idx, pat in enumerate(solution["patterns"]):
            assert "cuts" in pat, f"Pattern {idx} missing 'cuts' field"
            assert "quantity" in pat, f"Pattern {idx} missing 'quantity' field"
            assert isinstance(pat["quantity"], int) and pat["quantity"] > 0, (
                f"Pattern {idx} has non-positive or non-integer quantity"
            )

            total_width = 0
            for w_str, count in pat["cuts"].items():
                assert w_str in valid_widths, (
                    f"Pattern {idx} uses invalid width {w_str}"
                )
                assert isinstance(count, int) and count > 0, (
                    f"Pattern {idx} has invalid count {count} for width {w_str}"
                )
                total_width += int(w_str) * count

            assert total_width <= ROLL_WIDTH, (
                f"Pattern {idx} exceeds roll width: {pat['cuts']} sums to "
                f"{total_width} > {ROLL_WIDTH}"
            )

    def test_demands_satisfied(self, solution):
        produced = {str(w): 0 for w in WIDTHS}
        for pat in solution["patterns"]:
            for w_str, count in pat["cuts"].items():
                if w_str in produced:
                    produced[w_str] += count * pat["quantity"]

        for order in ORDERS:
            w_str = str(order["width"])
            assert produced[w_str] >= order["demand"], (
                f"Demand not satisfied for width {w_str}: produced "
                f"{produced[w_str]}, required {order['demand']}"
            )

    def test_pattern_quantities_sum_to_objective(self, solution):
        total = sum(p["quantity"] for p in solution["patterns"])
        assert total == solution["integer_objective"], (
            f"Sum of pattern quantities ({total}) does not match "
            f"integer_objective ({solution['integer_objective']})"
        )


class TestWasteAndMetrics:
    def test_total_waste_correct(self, solution):
        expected = solution["integer_objective"] * ROLL_WIDTH - TOTAL_AREA
        assert abs(solution["total_waste"] - expected) <= 1, (
            f"total_waste incorrect: got {solution['total_waste']}, expected "
            f"{expected} (= {solution['integer_objective']}*{ROLL_WIDTH} - "
            f"{TOTAL_AREA})"
        )

    def test_total_waste_nonnegative(self, solution):
        assert solution["total_waste"] >= 0, (
            f"total_waste should be non-negative, got {solution['total_waste']}"
        )


class TestOptimizationQuality:
    def test_multiple_iterations(self, solution):
        assert solution["optimization_iterations"] >= 2, (
            "Optimization should perform at least 2 iterations"
        )

    def test_patterns_beyond_initial(self, solution):
        assert solution["num_distinct_patterns"] > N, (
            f"Optimization should explore more than the {N} initial "
            f"patterns; got {solution['num_distinct_patterns']}"
        )

    def test_lower_bound_better_than_basic(self, solution):
        """The lower bound must be strictly below the naive upper bound,
        confirming that the optimization actually produced a tight bound."""
        assert solution["lower_bound"] < BASIC_UB, (
            f"Lower bound {solution['lower_bound']:.4f} should be strictly "
            f"less than the basic upper bound {BASIC_UB}"
        )
