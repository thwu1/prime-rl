
import json
import os
import pytest

SOLUTION_PATH = "/app/output/solution.json"

# Ground-truth problem parameters derived from the environment data files:
# stock_width = active material from stock_specs.toml
# net_demands = aggregate(batch_q1 + batch_q2 + batch_q3) - canceled - prior_run fulfillments
STOCK_WIDTH = 5600
WIDTHS = [2200, 1520, 1380, 1120, 930, 840, 770, 680, 520, 410, 350, 280, 220, 190, 140]
NET_DEMANDS = [42, 68, 33, 57, 84, 41, 72, 29, 63, 91, 38, 55, 47, 82, 96]
KNOWN_OPTIMAL = 113


@pytest.fixture
def solution():
    assert os.path.exists(SOLUTION_PATH), (
        f"Solution file not found at {SOLUTION_PATH}"
    )
    with open(SOLUTION_PATH) as f:
        data = json.load(f)
    return data


class TestSolutionFormat:
    def test_solution_file_exists(self):
        assert os.path.exists(SOLUTION_PATH), (
            f"Solution file not found at {SOLUTION_PATH}"
        )

    def test_solution_is_valid_json(self):
        with open(SOLUTION_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Solution must be a JSON object"

    def test_has_objective(self, solution):
        assert "objective" in solution, "Solution must have 'objective' field"
        assert isinstance(solution["objective"], int), "objective must be an integer"
        assert solution["objective"] > 0, "objective must be positive"

    def test_has_patterns(self, solution):
        assert "patterns" in solution, "Solution must have 'patterns' field"
        assert isinstance(solution["patterns"], list), "patterns must be a list"
        assert len(solution["patterns"]) > 0, "patterns must be non-empty"

    def test_pattern_entries_are_well_formed(self, solution):
        n_items = len(WIDTHS)
        for i, entry in enumerate(solution["patterns"]):
            assert "pattern" in entry, f"Pattern {i} missing 'pattern' field"
            assert "count" in entry, f"Pattern {i} missing 'count' field"
            assert isinstance(entry["pattern"], list), (
                f"Pattern {i}: pattern must be a list"
            )
            assert len(entry["pattern"]) == n_items, (
                f"Pattern {i}: pattern length {len(entry['pattern'])} != {n_items}"
            )
            assert isinstance(entry["count"], int), (
                f"Pattern {i}: count must be an integer"
            )
            assert entry["count"] > 0, f"Pattern {i}: count must be positive"
            for j, val in enumerate(entry["pattern"]):
                assert isinstance(val, int), (
                    f"Pattern {i}, item {j}: value must be integer"
                )
                assert val >= 0, (
                    f"Pattern {i}, item {j}: value must be non-negative"
                )


class TestFeasibility:
    def test_patterns_respect_stock_width(self, solution):
        for i, entry in enumerate(solution["patterns"]):
            pat = entry["pattern"]
            total_width = sum(pat[j] * WIDTHS[j] for j in range(len(WIDTHS)))
            assert total_width <= STOCK_WIDTH, (
                f"Pattern {i} total width {total_width} exceeds "
                f"stock width {STOCK_WIDTH}: pattern={pat}"
            )

    def test_all_demands_met(self, solution):
        n_items = len(WIDTHS)
        produced = [0] * n_items
        for entry in solution["patterns"]:
            for j in range(n_items):
                produced[j] += entry["pattern"][j] * entry["count"]
        for i in range(n_items):
            assert produced[i] >= NET_DEMANDS[i], (
                f"Item {i} (width={WIDTHS[i]}): "
                f"produced {produced[i]} < demand {NET_DEMANDS[i]}"
            )


class TestOptimality:
    def test_objective_matches_pattern_counts(self, solution):
        total_rolls = sum(entry["count"] for entry in solution["patterns"])
        assert solution["objective"] == total_rolls, (
            f"Stated objective {solution['objective']} != "
            f"sum of pattern counts {total_rolls}"
        )

    def test_objective_at_most_optimal(self, solution):
        assert solution["objective"] <= KNOWN_OPTIMAL, (
            f"Solution uses {solution['objective']} rolls, "
            f"which exceeds the minimum achievable. "
            f"An exact optimization method is required."
        )
