"""
Verification tests for the Cutting Stock column generation task.
Validates solution against known expected instance derived from the
production database (pending orders + demand adjustments).
"""


import json
import math
import os

import pulp
import pytest

# Expected instance parameters (ground truth from DB + adjustments).
# Agent must independently discover these by exploring the environment.
EXPECTED_ROLL_WIDTH = 1000
EXPECTED_WIDTHS = [467, 333, 295, 258, 231, 197, 168, 150, 137, 125,
                   113, 99, 89, 76, 63, 52, 41, 33, 27, 21]
EXPECTED_DEMANDS = [21, 44, 37, 28, 15, 31, 42, 55, 23, 18,
                    62, 41, 32, 48, 57, 39, 73, 86, 54, 93]
N_ITEMS = len(EXPECTED_WIDTHS)


def load_solution():
    with open("/app/output/solution.json") as f:
        return json.load(f)


class TestSolutionFormat:
    """Verify the solution file exists and has the correct structure."""

    def test_solution_file_exists(self):
        assert os.path.isfile("/app/output/solution.json"), (
            "Solution file not found at /app/output/solution.json"
        )

    def test_required_keys(self):
        sol = load_solution()
        assert "lp_bound" in sol, "Missing 'lp_bound' in solution"
        assert "num_rolls" in sol, "Missing 'num_rolls' in solution"
        assert "patterns" in sol, "Missing 'patterns' in solution"

    def test_types(self):
        sol = load_solution()
        assert isinstance(sol["lp_bound"], (int, float))
        assert isinstance(sol["num_rolls"], int)
        assert isinstance(sol["patterns"], list)
        assert len(sol["patterns"]) > 0, "No patterns in solution"
        for p in sol["patterns"]:
            assert "pattern" in p, "Pattern entry missing 'pattern' key"
            assert "num_rolls" in p, "Pattern entry missing 'num_rolls' key"

    def test_correct_item_count(self):
        """Solution must have patterns with exactly N_ITEMS entries."""
        sol = load_solution()
        for idx, p in enumerate(sol["patterns"]):
            assert len(p["pattern"]) == N_ITEMS, (
                f"Pattern {idx} has {len(p['pattern'])} entries, "
                f"expected {N_ITEMS} (one per distinct piece width)"
            )


class TestFeasibility:
    """Verify that the solution is feasible against the expected instance."""

    def test_patterns_do_not_exceed_roll_width(self):
        sol = load_solution()
        for idx, p in enumerate(sol["patterns"]):
            pat = p["pattern"]
            for count in pat:
                assert isinstance(count, int) and count >= 0, (
                    f"Pattern {idx} has non-integer or negative count: {count}"
                )
            total_width = sum(
                EXPECTED_WIDTHS[i] * pat[i] for i in range(N_ITEMS)
            )
            assert total_width <= EXPECTED_ROLL_WIDTH, (
                f"Pattern {idx} uses width {total_width}, "
                f"exceeds roll width {EXPECTED_ROLL_WIDTH}"
            )

    def test_all_demands_met(self):
        sol = load_solution()
        supplied = [0] * N_ITEMS
        for p in sol["patterns"]:
            pat = p["pattern"]
            rolls = p["num_rolls"]
            for i in range(N_ITEMS):
                supplied[i] += pat[i] * rolls

        for i in range(N_ITEMS):
            assert supplied[i] >= EXPECTED_DEMANDS[i], (
                f"Item {i} (width={EXPECTED_WIDTHS[i]}): supplied "
                f"{supplied[i]} < demand {EXPECTED_DEMANDS[i]}"
            )

    def test_pattern_rolls_positive(self):
        sol = load_solution()
        for idx, p in enumerate(sol["patterns"]):
            assert isinstance(p["num_rolls"], int) and p["num_rolls"] > 0, (
                f"Pattern {idx} has invalid num_rolls: {p['num_rolls']}"
            )

    def test_num_rolls_consistent(self):
        sol = load_solution()
        total = sum(p["num_rolls"] for p in sol["patterns"])
        assert total == sol["num_rolls"], (
            f"Reported num_rolls={sol['num_rolls']} != "
            f"sum of pattern rolls={total}"
        )


class TestLPBound:
    """Verify the LP bound is valid and accurate."""

    def test_lp_bound_at_least_trivial(self):
        """LP bound >= trivial continuous lower bound."""
        sol = load_solution()
        trivial_lb = sum(
            w * d for w, d in zip(EXPECTED_WIDTHS, EXPECTED_DEMANDS)
        ) / EXPECTED_ROLL_WIDTH
        assert sol["lp_bound"] >= trivial_lb - 0.01, (
            f"LP bound {sol['lp_bound']:.4f} < trivial LB {trivial_lb:.4f}"
        )

    def test_lp_bound_at_most_integer(self):
        """LP relaxation bound cannot exceed integer solution."""
        sol = load_solution()
        assert sol["lp_bound"] <= sol["num_rolls"] + 0.01, (
            f"LP bound {sol['lp_bound']:.4f} > "
            f"integer solution {sol['num_rolls']}"
        )

    def test_lp_bound_accuracy(self):
        """Verify LP bound by running independent column generation."""
        sol = load_solution()
        widths = EXPECTED_WIDTHS
        demands = EXPECTED_DEMANDS
        roll_w = EXPECTED_ROLL_WIDTH
        n = N_ITEMS

        # Initialize with homogeneous patterns
        patterns = []
        for i in range(n):
            p = [0] * n
            p[i] = roll_w // widths[i]
            patterns.append(p)

        ref_lb = None
        for _ in range(500):
            prob = pulp.LpProblem("RefRMP", pulp.LpMinimize)
            m = len(patterns)
            x = [pulp.LpVariable(f"x{j}", lowBound=0) for j in range(m)]
            prob += pulp.lpSum(x)
            for i in range(n):
                prob += (
                    pulp.lpSum(patterns[j][i] * x[j] for j in range(m))
                    >= demands[i],
                    f"d{i}",
                )
            prob.solve(pulp.PULP_CBC_CMD(msg=0))
            ref_lb = pulp.value(prob.objective)

            duals = []
            for i in range(n):
                pi_val = prob.constraints[f"d{i}"].pi
                duals.append(pi_val if pi_val is not None else 0.0)

            # Pricing via unbounded knapsack DP
            dp = [0.0] * (roll_w + 1)
            choice = [-1] * (roll_w + 1)
            for c in range(1, roll_w + 1):
                for i in range(n):
                    if widths[i] <= c:
                        val = dp[c - widths[i]] + duals[i]
                        if val > dp[c] + 1e-10:
                            dp[c] = val
                            choice[c] = i

            if dp[roll_w] <= 1.0 + 1e-6:
                break

            new_pat = [0] * n
            c = roll_w
            while c > 0 and choice[c] >= 0:
                new_pat[choice[c]] += 1
                c -= widths[choice[c]]

            if new_pat not in patterns:
                patterns.append(new_pat)
            else:
                break

        assert ref_lb is not None, "Reference column generation failed"
        assert abs(sol["lp_bound"] - ref_lb) < 2.0, (
            f"Agent LP bound {sol['lp_bound']:.4f} differs from "
            f"reference {ref_lb:.4f} by more than 2.0"
        )


class TestSolutionQuality:
    """Verify solution quality relative to LP bound."""

    def test_integer_at_least_lp_ceiling(self):
        sol = load_solution()
        lp_ceil = math.ceil(sol["lp_bound"] - 1e-6)
        assert sol["num_rolls"] >= lp_ceil, (
            f"num_rolls {sol['num_rolls']} < ceil(lp_bound) = {lp_ceil}"
        )

    def test_integer_within_gap(self):
        """Integer solution must be within ceil(LP_bound) + 2."""
        sol = load_solution()
        lp_ceil = math.ceil(sol["lp_bound"] - 1e-6)
        assert sol["num_rolls"] <= lp_ceil + 2, (
            f"num_rolls {sol['num_rolls']} > ceil(lp_bound)+2 = "
            f"{lp_ceil + 2}. Solution quality is too poor."
        )
