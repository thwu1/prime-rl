import os
import pytest


def get_test_results():
    """Parse the TestRunner output to get individual test results."""
    output_file = "/tests/test_output.txt"
    if not os.path.exists(output_file):
        return {}, "Output file not found - compilation may have failed"

    with open(output_file) as f:
        raw_output = f.read()

    results = {}
    for line in raw_output.strip().split('\n'):
        line = line.strip()
        if line.startswith('PASS: '):
            name = line[6:].strip()
            results[name] = True
        elif line.startswith('FAIL: '):
            name = line[6:].strip()
            results[name] = False

    return results, raw_output

results, raw_output = get_test_results()

EXPECTED_TESTS = [
    "constant_folding_basic",
    "constant_folding_null",
    "constant_folding_div_zero",
    "constant_folding_child_plan",
    "boolean_simp_and_true",
    "boolean_simp_and_false",
    "boolean_simp_or_false",
    "boolean_simp_not_not",
    "boolean_simp_idempotent",
    "boolean_simp_complement_nonnullable",
    "boolean_simp_complement_nullable",
    "boolean_simp_absorption",
    "boolean_simp_common_factor",
    "boolean_simp_different_ops",
    "null_prop_nonnullable_isnull",
    "null_prop_nonnullable_isnotnull",
    "null_prop_nullable_unchanged",
    "null_prop_nested_plan",
    "predicate_pushdown_basic",
    "predicate_pushdown_both_sides",
    "predicate_pushdown_stacked",
    "combined_all_rules",
]

def test_compilation_succeeded():
    """Verify the Java code compiled without errors."""
    errors_file = "/tests/compile_errors.txt"
    if os.path.exists(errors_file):
        with open(errors_file) as f:
            errors = f.read().strip()
        assert errors == "", f"Compilation errors:\n{errors}"

@pytest.mark.parametrize("test_name", EXPECTED_TESTS)
def test_optimizer(test_name):
    """Verify each individual optimizer test passed."""
    assert test_name in results, (
        f"Test '{test_name}' did not run. Raw output:\n{raw_output}"
    )
    assert results[test_name], (
        f"Test '{test_name}' failed. See test output for details."
    )

def test_all_tests_ran():
    """Verify all expected tests were executed."""
    missing = [t for t in EXPECTED_TESTS if t not in results]
    assert len(missing) == 0, f"Tests did not run: {missing}"
