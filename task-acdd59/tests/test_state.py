
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# Expected final states for all 10 programs
EXPECTED_STATES = {
    "p1_basic_arith": {"a": 12, "b": 4, "c": 8, "d": 16},
    "p2_mul_div_swap": {"x": 20, "y": 5, "p": 4, "q": 100},
    "p3_nested_arith": {"a": 30, "b": 6, "c": 1},
    "p4_condition_flip": {"a": 10, "b": 3, "r": 3},
    "p5_equality_swap": {"a": 3, "b": 7, "c": 5, "r": 100},
    "p6_logic_swap": {"a": 5, "b": 10, "r": 1},
    "p7_loop_reverse": {"i": 4, "s": -45},
    "p8_div_zero_flip": {"x": 10, "y": 0, "z": 0, "w": 99},
    "p9_mul_zero_error": "ERROR",
    "p10_unary_swap": {"a": 7, "b": 7, "c": -7},
}

# Expected step counts (total abstract machine transitions)
EXPECTED_STEPS = {
    "p1_basic_arith": 14,
    "p2_mul_div_swap": 14,
    "p3_nested_arith": 13,
    "p4_condition_flip": 13,
    "p5_equality_swap": 12,
    "p6_logic_swap": 14,
    "p7_loop_reverse": 80,
    "p8_div_zero_flip": 11,
    "p9_mul_zero_error": 8,
    "p10_unary_swap": 10,
}

# Expected rule histograms (innermost rule counts)
# Keys are strings (JSON object keys must be strings)
EXPECTED_HISTOGRAMS = {
    "p1_basic_arith": {"1": 4, "3": 4, "5": 4, "9": 1, "12": 1},
    "p2_mul_div_swap": {"1": 4, "3": 4, "5": 4, "15": 1, "18": 1},
    "p3_nested_arith": {"1": 4, "3": 3, "5": 3, "9": 1, "12": 1, "18": 1},
    "p4_condition_flip": {"1": 4, "3": 3, "5": 3, "18": 1, "38": 1, "65": 1},
    "p5_equality_swap": {"1": 2, "3": 4, "5": 4, "50": 1, "65": 1},
    "p6_logic_swap": {"1": 4, "3": 3, "5": 3, "30": 1, "47": 1, "58": 1, "65": 1},
    "p7_loop_reverse": {
        "1": 25, "3": 2, "5": 14, "12": 12,
        "42": 6, "43": 1, "67": 7, "69": 1, "70": 6, "77": 6,
    },
    "p8_div_zero_flip": {"1": 2, "3": 4, "5": 4, "15": 1},
    "p9_mul_zero_error": {"1": 2, "3": 3, "5": 2, "19": 1},
    "p10_unary_swap": {"1": 2, "3": 3, "5": 3, "25": 1, "27": 1},
}

# Expected operator mapping (canonical names)
EXPECTED_MAPPING = {
    "binary_+": "subtraction",
    "binary_-": "addition",
    "binary_*": "division",
    "binary_/": "multiplication",
    "binary_%": "modulo",
    "unary_+": "negation",
    "unary_-": "identity",
    "<": "greater_than",
    "<=": "greater_equal",
    ">": "less_than",
    ">=": "less_equal",
    "==": "not_equal",
    "!=": "equal",
    "&&": "disjunction",
    "||": "conjunction",
    "!": "negation",
}


def load_results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must be a JSON object"
    return data


class TestStructure:
    def test_results_file_exists(self):
        load_results()

    def test_has_operator_mapping(self):
        data = load_results()
        assert "operator_mapping" in data, "Missing operator_mapping key"
        assert isinstance(data["operator_mapping"], dict)

    def test_has_programs(self):
        data = load_results()
        assert "programs" in data, "Missing programs key"
        assert isinstance(data["programs"], dict)

    def test_all_programs_present(self):
        data = load_results()
        for prog in EXPECTED_STATES:
            assert prog in data["programs"], f"Missing result for {prog}"

    def test_program_fields(self):
        data = load_results()
        for prog in EXPECTED_STATES:
            if prog not in data["programs"]:
                continue
            entry = data["programs"][prog]
            assert "final_state" in entry, f"{prog}: missing final_state"
            assert "step_count" in entry, f"{prog}: missing step_count"
            assert "rule_histogram" in entry, f"{prog}: missing rule_histogram"


class TestSchemaValidation:
    def test_schema_valid(self):
        import jsonschema
        schema_path = "/app/schema/output_schema.json"
        assert os.path.exists(schema_path), "Schema file not found"
        with open(schema_path) as f:
            schema = json.load(f)
        data = load_results()
        jsonschema.validate(instance=data, schema=schema)


@pytest.mark.parametrize("op,expected", list(EXPECTED_MAPPING.items()))
class TestOperatorMapping:
    def test_mapping(self, op, expected):
        data = load_results()
        mapping = data["operator_mapping"]
        assert op in mapping, f"Missing mapping for operator '{op}'"
        actual = mapping[op].lower().strip()
        assert actual == expected, (
            f"Operator '{op}': expected '{expected}', got '{mapping[op]}'"
        )


@pytest.mark.parametrize("prog_name", list(EXPECTED_STATES.keys()))
class TestFinalState:
    def test_state(self, prog_name):
        data = load_results()
        assert prog_name in data["programs"], f"Missing {prog_name}"
        actual = data["programs"][prog_name]["final_state"]
        expected = EXPECTED_STATES[prog_name]
        if isinstance(expected, str):
            assert actual == expected, (
                f"{prog_name}: expected '{expected}', got {actual!r}"
            )
        else:
            assert isinstance(actual, dict), (
                f"{prog_name}: expected dict, got {type(actual).__name__}"
            )
            for var, val in expected.items():
                assert var in actual, (
                    f"{prog_name}: missing variable '{var}'"
                )
                assert actual[var] == val, (
                    f"{prog_name}: {var} = {actual[var]}, expected {val}"
                )
            for var in actual:
                assert var in expected, (
                    f"{prog_name}: unexpected variable '{var}'"
                )


@pytest.mark.parametrize("prog_name", list(EXPECTED_STEPS.keys()))
class TestStepCount:
    def test_steps(self, prog_name):
        data = load_results()
        assert prog_name in data["programs"], f"Missing {prog_name}"
        actual = data["programs"][prog_name]["step_count"]
        expected = EXPECTED_STEPS[prog_name]
        assert actual == expected, (
            f"{prog_name}: step_count = {actual}, expected {expected}"
        )


@pytest.mark.parametrize("prog_name", list(EXPECTED_HISTOGRAMS.keys()))
class TestRuleHistogram:
    def test_histogram(self, prog_name):
        data = load_results()
        assert prog_name in data["programs"], f"Missing {prog_name}"
        actual = data["programs"][prog_name]["rule_histogram"]
        expected = EXPECTED_HISTOGRAMS[prog_name]
        assert isinstance(actual, dict), (
            f"{prog_name}: rule_histogram must be an object"
        )
        # Convert keys to strings for comparison
        actual_str = {str(k): v for k, v in actual.items()}
        for rule, count in expected.items():
            assert rule in actual_str, (
                f"{prog_name}: missing rule {rule} in histogram"
            )
            assert actual_str[rule] == count, (
                f"{prog_name}: rule {rule} count = {actual_str[rule]}, expected {count}"
            )
        for rule in actual_str:
            assert rule in expected, (
                f"{prog_name}: unexpected rule {rule} in histogram"
            )
