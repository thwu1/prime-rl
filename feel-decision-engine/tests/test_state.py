"""
Tests for the FEEL decision table engine.

"""
import subprocess
import json
import os
import tempfile
import pytest


def run_engine(table, input_data):
    """Run the FEEL decision table engine and return parsed output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        table_path = os.path.join(tmpdir, "table.json")
        input_path = os.path.join(tmpdir, "input.json")
        with open(table_path, "w") as f:
            json.dump(table, f)
        with open(input_path, "w") as f:
            json.dump(input_data, f)

        result = subprocess.run(
            ["/app/run.sh", table_path, input_path],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Engine failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        output = result.stdout.strip()
        if output == "null":
            return None
        return json.loads(output)


# ========== Baseline tests ==========

class TestBaseline:

    def test_string_equality(self):
        table = {
            "hitPolicy": "UNIQUE", "aggregation": "NONE",
            "inputs": [{"name": "color", "type": "string"}],
            "outputs": [{"name": "hex", "type": "string"}],
            "rules": [
                {"inputs": ['"red"'], "outputs": ['"#FF0000"']},
                {"inputs": ['"green"'], "outputs": ['"#00FF00"']},
                {"inputs": ['"blue"'], "outputs": ['"#0000FF"']}
            ]
        }
        result = run_engine(table, {"color": "green"})
        assert result == {"hex": "#00FF00"}

    def test_number_comparison(self):
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "label", "type": "string"}],
            "rules": [
                {"inputs": [">= 100"], "outputs": ['"high"']},
                {"inputs": ["< 100"], "outputs": ['"low"']}
            ]
        }
        result = run_engine(table, {"x": 150})
        assert result == {"label": "high"}

    def test_wildcard(self):
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "result", "type": "string"}],
            "rules": [
                {"inputs": ["-"], "outputs": ['"matched"']}
            ]
        }
        result = run_engine(table, {"x": 42})
        assert result == {"result": "matched"}

    def test_no_match_returns_null(self):
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "result", "type": "string"}],
            "rules": [
                {"inputs": ["> 100"], "outputs": ['"big"']}
            ]
        }
        result = run_engine(table, {"x": 5})
        assert result is None

    def test_multi_input_columns(self):
        table = {
            "hitPolicy": "UNIQUE", "aggregation": "NONE",
            "inputs": [
                {"name": "type", "type": "string"},
                {"name": "amount", "type": "number"}
            ],
            "outputs": [{"name": "discount", "type": "number"}],
            "rules": [
                {"inputs": ['"business"', ">= 1000"], "outputs": ["0.15"]},
                {"inputs": ['"business"', "< 1000"], "outputs": ["0.05"]},
                {"inputs": ['"individual"', "-"], "outputs": ["0"]}
            ]
        }
        result = run_engine(table, {"type": "business", "amount": 1500})
        assert result == {"discount": 0.15}

    def test_hit_policy_first(self):
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "y", "type": "number"}],
            "rules": [
                {"inputs": [">= 5"], "outputs": ["100"]},
                {"inputs": ["<= 15"], "outputs": ["200"]}
            ]
        }
        result = run_engine(table, {"x": 10})
        assert result == {"y": 100}

    def test_range_both_inclusive_symmetric(self):
        """[a..b] — symmetric case."""
        table = {
            "hitPolicy": "UNIQUE", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "in_range", "type": "boolean"}],
            "rules": [
                {"inputs": ["[1..10]"], "outputs": ["true"]},
                {"inputs": ["< 1"], "outputs": ["false"]},
                {"inputs": ["> 10"], "outputs": ["false"]}
            ]
        }
        result = run_engine(table, {"x": 5})
        assert result == {"in_range": True}

    def test_date_comparison(self):
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "d", "type": "date"}],
            "outputs": [{"name": "period", "type": "string"}],
            "rules": [
                {"inputs": ['>= date("2024-01-01")'], "outputs": ['"current"']},
                {"inputs": ["-"], "outputs": ['"past"']}
            ]
        }
        result = run_engine(table, {"d": "2024-06-15"})
        assert result == {"period": "current"}


# ========== Range boundary tests ==========

class TestRangeBoundaries:

    def test_lower_inclusive_upper_exclusive(self):
        """[80..90) at lower boundary: 80 should match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "score", "type": "number"}],
            "outputs": [{"name": "grade", "type": "string"}],
            "rules": [
                {"inputs": ["[90..100]"], "outputs": ['"A"']},
                {"inputs": ["[80..90)"], "outputs": ['"B"']},
                {"inputs": ["[70..80)"], "outputs": ['"C"']},
                {"inputs": ["-"], "outputs": ['"F"']}
            ]
        }
        result = run_engine(table, {"score": 80})
        assert result == {"grade": "B"}, "score=80 should match [80..90)"

    def test_lower_inclusive_upper_exclusive_at_upper(self):
        """[80..90) at upper boundary: 90 should NOT match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "score", "type": "number"}],
            "outputs": [{"name": "grade", "type": "string"}],
            "rules": [
                {"inputs": ["[80..90)"], "outputs": ['"B"']},
                {"inputs": ["-"], "outputs": ['"other"']}
            ]
        }
        result = run_engine(table, {"score": 90})
        assert result == {"grade": "other"}, "score=90 should NOT match [80..90)"

    def test_lower_exclusive_upper_inclusive(self):
        """(0..100] at upper boundary: 100 should match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "result", "type": "string"}],
            "rules": [
                {"inputs": ["(0..100]"], "outputs": ['"in_range"']},
                {"inputs": ["-"], "outputs": ['"out_of_range"']}
            ]
        }
        result = run_engine(table, {"x": 100})
        assert result == {"result": "in_range"}, "x=100 should match (0..100]"

    def test_lower_exclusive_upper_inclusive_at_lower(self):
        """(0..100] at lower boundary: 0 should NOT match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "result", "type": "string"}],
            "rules": [
                {"inputs": ["(0..100]"], "outputs": ['"in_range"']},
                {"inputs": ["-"], "outputs": ['"out_of_range"']}
            ]
        }
        result = run_engine(table, {"x": 0})
        assert result == {"result": "out_of_range"}, "x=0 should NOT match (0..100]"


# ========== Negation tests ==========

class TestNegation:

    def test_negation_single_value(self):
        """not("rejected") with input "approved" should match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "status", "type": "string"}],
            "outputs": [{"name": "allow", "type": "boolean"}],
            "rules": [
                {"inputs": ['not("rejected")'], "outputs": ["true"]},
                {"inputs": ["-"], "outputs": ["false"]}
            ]
        }
        result = run_engine(table, {"status": "approved"})
        assert result == {"allow": True}

    def test_negation_range(self):
        """not([0..17]) with input 25 should match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "age", "type": "number"}],
            "outputs": [{"name": "category", "type": "string"}],
            "rules": [
                {"inputs": ["not([0..17])"], "outputs": ['"adult"']},
                {"inputs": ["-"], "outputs": ['"minor"']}
            ]
        }
        result = run_engine(table, {"age": 25})
        assert result == {"category": "adult"}


# ========== Disjunction tests ==========

class TestDisjunction:

    def test_disjunction_strings(self):
        '''"Saturday", "Sunday" with input "Sunday" should match.'''
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "day", "type": "string"}],
            "outputs": [{"name": "type", "type": "string"}],
            "rules": [
                {"inputs": ['"Saturday", "Sunday"'], "outputs": ['"weekend"']},
                {"inputs": ["-"], "outputs": ['"weekday"']}
            ]
        }
        result = run_engine(table, {"day": "Sunday"})
        assert result == {"type": "weekend"}

    def test_disjunction_numbers(self):
        """200, 201, 204 with input 204 should match."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "code", "type": "number"}],
            "outputs": [{"name": "status", "type": "string"}],
            "rules": [
                {"inputs": ["200, 201, 204"], "outputs": ['"success"']},
                {"inputs": ["400, 401, 403, 404"], "outputs": ['"client_error"']},
                {"inputs": ["-"], "outputs": ['"other"']}
            ]
        }
        result = run_engine(table, {"code": 404})
        assert result == {"status": "client_error"}


# ========== Null propagation tests (coupled with negation) ==========

class TestNullPropagation:

    def test_negation_comparison_null_interaction(self):
        """not(> 10) with null input: comparison must yield null, not(null) must yield null.
        If only negation is fixed but null propagation is not, not(false)=true incorrectly matches."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "result", "type": "string"}],
            "rules": [
                {"inputs": ["not(> 10)"], "outputs": ['"matched"']},
                {"inputs": ["-"], "outputs": ['"fallback"']}
            ]
        }
        result = run_engine(table, {"x": None})
        assert result == {"result": "fallback"}, \
            "null through not(> 10) must propagate as null, not match"

    def test_negation_range_null_interaction(self):
        """not([0..17]) with null input: range must yield null, not(null) must yield null.
        If only negation is fixed but range null propagation is not, not(false)=true incorrectly matches."""
        table = {
            "hitPolicy": "FIRST", "aggregation": "NONE",
            "inputs": [{"name": "age", "type": "number"}],
            "outputs": [{"name": "category", "type": "string"}],
            "rules": [
                {"inputs": ["not([0..17])"], "outputs": ['"adult"']},
                {"inputs": ["-"], "outputs": ['"fallback"']}
            ]
        }
        result = run_engine(table, {"age": None})
        assert result == {"category": "fallback"}, \
            "null through not([0..17]) must propagate as null, not match"


# ========== Hit policy tests ==========

class TestHitPolicies:

    def test_unique_violation(self):
        """UNIQUE with overlapping rules should produce _error."""
        table = {
            "hitPolicy": "UNIQUE", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "y", "type": "number"}],
            "rules": [
                {"inputs": [">= 5"], "outputs": ["1"]},
                {"inputs": ["<= 15"], "outputs": ["2"]}
            ]
        }
        result = run_engine(table, {"x": 10})
        assert isinstance(result, dict)
        assert "_error" in result, "UNIQUE should error when multiple rules match"

    def test_any_same_outputs(self):
        """ANY with identical outputs should return the output."""
        table = {
            "hitPolicy": "ANY", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "category", "type": "string"}],
            "rules": [
                {"inputs": [">= 0"], "outputs": ['"non-negative"']},
                {"inputs": ["[0..1000]"], "outputs": ['"non-negative"']}
            ]
        }
        result = run_engine(table, {"x": 50})
        assert result == {"category": "non-negative"}

    def test_any_violation(self):
        """ANY with different outputs should produce _error."""
        table = {
            "hitPolicy": "ANY", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "y", "type": "number"}],
            "rules": [
                {"inputs": [">= 5"], "outputs": ["100"]},
                {"inputs": ["<= 15"], "outputs": ["200"]}
            ]
        }
        result = run_engine(table, {"x": 10})
        assert isinstance(result, dict)
        assert "_error" in result, "ANY should error when matched outputs differ"

    def test_rule_order(self):
        """RULE_ORDER should return all matches in definition order."""
        table = {
            "hitPolicy": "RULE_ORDER", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "rule", "type": "string"}],
            "rules": [
                {"inputs": ["> 0"], "outputs": ['"positive"']},
                {"inputs": ["> 10"], "outputs": ['"big"']},
                {"inputs": ["> 100"], "outputs": ['"huge"']}
            ]
        }
        result = run_engine(table, {"x": 50})
        assert isinstance(result, list), "RULE_ORDER should return a list"
        assert len(result) == 2
        assert result[0] == {"rule": "positive"}, "First match should be 'positive'"
        assert result[1] == {"rule": "big"}, "Second match should be 'big'"


# ========== PRIORITY hit policy tests ==========

class TestPriority:

    def test_priority_basic(self):
        """PRIORITY returns highest-priority output when multiple rules match."""
        table = {
            "hitPolicy": "PRIORITY", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "level", "type": "string",
                         "outputValues": ["critical", "warning", "info"]}],
            "rules": [
                {"inputs": ["> 0"], "outputs": ['"info"']},
                {"inputs": ["> 50"], "outputs": ['"warning"']},
                {"inputs": ["> 90"], "outputs": ['"critical"']}
            ]
        }
        # x=95 matches all three: info(idx 2), warning(idx 1), critical(idx 0)
        result = run_engine(table, {"x": 95})
        assert result == {"level": "critical"}, \
            "PRIORITY should return highest-priority (earliest in outputValues)"

    def test_priority_non_first_rule_wins(self):
        """PRIORITY: a non-first matching rule can win if its output has higher priority."""
        table = {
            "hitPolicy": "PRIORITY", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "level", "type": "string",
                         "outputValues": ["A", "B", "C"]}],
            "rules": [
                {"inputs": ["> 0"], "outputs": ['"C"']},
                {"inputs": ["> 10"], "outputs": ['"A"']},
                {"inputs": ["> 5"], "outputs": ['"B"']}
            ]
        }
        # x=20 matches all: C(idx 2), A(idx 0), B(idx 1) -> A wins
        result = run_engine(table, {"x": 20})
        assert result == {"level": "A"}

    def test_priority_single_match(self):
        """PRIORITY with only one matching rule returns that match."""
        table = {
            "hitPolicy": "PRIORITY", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "level", "type": "string",
                         "outputValues": ["A", "B", "C"]}],
            "rules": [
                {"inputs": ["> 100"], "outputs": ['"A"']},
                {"inputs": ["> 50"], "outputs": ['"B"']},
                {"inputs": ["> 0"], "outputs": ['"C"']}
            ]
        }
        # x=30 matches only rule 3
        result = run_engine(table, {"x": 30})
        assert result == {"level": "C"}


# ========== COLLECT aggregation tests ==========

class TestCollect:

    def test_collect_list(self):
        """COLLECT+NONE returns all outputs as a list."""
        table = {
            "hitPolicy": "COLLECT", "aggregation": "NONE",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "tag", "type": "string"}],
            "rules": [
                {"inputs": ["> 0"], "outputs": ['"positive"']},
                {"inputs": ["< 100"], "outputs": ['"small"']},
                {"inputs": ["-"], "outputs": ['"any"']}
            ]
        }
        result = run_engine(table, {"x": 50})
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == {"tag": "positive"}
        assert result[1] == {"tag": "small"}
        assert result[2] == {"tag": "any"}

    def test_collect_sum_decimal(self):
        """COLLECT+SUM must use decimal-precise arithmetic."""
        table = {
            "hitPolicy": "COLLECT", "aggregation": "SUM",
            "inputs": [{"name": "item", "type": "string"}],
            "outputs": [{"name": "price", "type": "number"}],
            "rules": [
                {"inputs": ["-"], "outputs": ["10.50"]},
                {"inputs": ["-"], "outputs": ["20.75"]},
                {"inputs": ["-"], "outputs": ["5.25"]}
            ]
        }
        result = run_engine(table, {"item": "any"})
        assert result == {"price": 36.5}, f"SUM should be 36.5, got {result}"

    def test_collect_min(self):
        """COLLECT+MIN should return the minimum value."""
        table = {
            "hitPolicy": "COLLECT", "aggregation": "MIN",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "val", "type": "number"}],
            "rules": [
                {"inputs": ["-"], "outputs": ["30"]},
                {"inputs": ["-"], "outputs": ["10"]},
                {"inputs": ["-"], "outputs": ["20"]}
            ]
        }
        result = run_engine(table, {"x": 1})
        assert result == {"val": 10}, f"MIN should be 10, got {result}"

    def test_collect_max(self):
        """COLLECT+MAX should return the maximum value."""
        table = {
            "hitPolicy": "COLLECT", "aggregation": "MAX",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "val", "type": "number"}],
            "rules": [
                {"inputs": ["-"], "outputs": ["30"]},
                {"inputs": ["-"], "outputs": ["10"]},
                {"inputs": ["-"], "outputs": ["20"]}
            ]
        }
        result = run_engine(table, {"x": 1})
        assert result == {"val": 30}

    def test_collect_count(self):
        """COLLECT+COUNT should return count of matched rules."""
        table = {
            "hitPolicy": "COLLECT", "aggregation": "COUNT",
            "inputs": [{"name": "x", "type": "number"}],
            "outputs": [{"name": "n", "type": "number"}],
            "rules": [
                {"inputs": ["> 0"], "outputs": ["1"]},
                {"inputs": ["> 10"], "outputs": ["1"]},
                {"inputs": ["> 100"], "outputs": ["1"]}
            ]
        }
        # x=50 matches rules 1 and 2 only
        result = run_engine(table, {"x": 50})
        assert result == {"n": 2}
