
"""Verification tests for compiler conformance UB analysis task."""

import subprocess
import json
import os
import pytest

TESTS_DIR = "/app/tests"
ANALYSIS_PATH = "/app/analysis.json"

# All 15 test files expected after completion
ALL_TESTS = [
    "t_compound_literal.c",
    "t_shift_ops.c",
    "t_designated_init.c",
    "t_vla_sizeof.c",
    "t_flexible_array.c",
    "t_integer_promotion.c",
    "t_sizeof_expr.c",
    "t_bitfield_width.c",
    "t_strict_alias.c",
    "t_signed_wrap.c",
    "t_sequence_mod.c",
    "t_neg_rshift.c",
    "t_irreducible_flow.c",
    "t_union_pun.c",
    "t_restrict_qual.c",
]

# Expected defect classifications
WRONG_EXPECTATION_FILES = {"t_integer_promotion.c", "t_sizeof_expr.c", "t_bitfield_width.c"}
UNDEFINED_BEHAVIOR_FILES = {"t_strict_alias.c", "t_signed_wrap.c", "t_sequence_mod.c"}
IMPLEMENTATION_DEFINED_FILES = {"t_neg_rshift.c"}
ALL_DEFECTIVE_FILES = WRONG_EXPECTATION_FILES | UNDEFINED_BEHAVIOR_FILES | IMPLEMENTATION_DEFINED_FILES

NEW_TESTS = ["t_irreducible_flow.c", "t_union_pun.c", "t_restrict_qual.c"]
COMPILERS = ["gcc", "clang"]
OPT_LEVELS = ["-O0", "-O2", "-O3"]


def compile_and_run(test_file, compiler, opt_level):
    """Compile a test file and run it. Returns (passed, message)."""
    src = os.path.join(TESTS_DIR, test_file)
    base = test_file.replace(".c", "")
    binary = f"/tmp/test_{base}_{compiler}_{opt_level.replace('-', '')}"

    compile_result = subprocess.run(
        [compiler, opt_level, "-std=c11", "-I/app", "-o", binary, src, "-lm"],
        capture_output=True, text=True, timeout=30
    )
    if compile_result.returncode != 0:
        return False, f"Compilation failed: {compile_result.stderr[:500]}"

    try:
        run_result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
    finally:
        if os.path.exists(binary):
            os.remove(binary)

    if run_result.returncode != 0:
        return False, (
            f"Runtime failure (exit {run_result.returncode}): "
            f"stdout={run_result.stdout.strip()}, "
            f"stderr={run_result.stderr.strip()}"
        )

    if "PASS" not in run_result.stdout:
        return False, f"No PASS in output: {run_result.stdout.strip()}"

    return True, "OK"


# --- File existence ---

class TestFilesExist:
    """All 15 test files must exist."""

    @pytest.mark.parametrize("test_file", ALL_TESTS)
    def test_file_exists(self, test_file):
        path = os.path.join(TESTS_DIR, test_file)
        assert os.path.exists(path), f"Test file {test_file} not found at {path}"


# --- Compile and run all tests at all optimization levels ---

@pytest.mark.parametrize("test_file", ALL_TESTS)
@pytest.mark.parametrize("compiler", COMPILERS)
@pytest.mark.parametrize("opt_level", OPT_LEVELS)
def test_compile_and_pass(test_file, compiler, opt_level):
    """Each test must compile and pass with the given compiler and opt level."""
    passed, msg = compile_and_run(test_file, compiler, opt_level)
    assert passed, f"{test_file} with {compiler} {opt_level}: {msg}"


# --- Wrong-expectation bug fix source checks ---

class TestWrongExpectationFixes:
    """Verify the three wrong-expectation tests no longer contain buggy assertions."""

    def test_integer_promotion_fixed(self):
        path = os.path.join(TESTS_DIR, "t_integer_promotion.c")
        with open(path) as f:
            content = f.read()
        normalized = content.replace(" ", "")
        assert "(x+y)==0)" not in normalized, \
            "Bug not fixed: (x + y) == 0 still present"

    def test_sizeof_expr_fixed(self):
        path = os.path.join(TESTS_DIR, "t_sizeof_expr.c")
        with open(path) as f:
            content = f.read()
        assert "x == 6" not in content, \
            "Bug not fixed: 'x == 6' still present"

    def test_bitfield_width_fixed(self):
        path = os.path.join(TESTS_DIR, "t_bitfield_width.c")
        with open(path) as f:
            content = f.read()
        normalized = content.replace(" ", "")
        assert "==18)" not in normalized, \
            "Bug not fixed: '== 18)' still present"


# --- UB fix source checks ---

class TestUBFixes:
    """Verify UB tests have been rewritten to remove undefined behavior."""

    def test_strict_alias_no_cast(self):
        """Strict aliasing violation (pointer cast to incompatible type) must be removed."""
        path = os.path.join(TESTS_DIR, "t_strict_alias.c")
        with open(path) as f:
            content = f.read()
        assert "(float *)&" not in content, \
            "Strict aliasing violation still present: (float *)& cast"

    def test_sequence_no_double_increment(self):
        """Sequence point violations must be eliminated."""
        path = os.path.join(TESTS_DIR, "t_sequence_mod.c")
        with open(path) as f:
            content = f.read()
        normalized = content.replace(" ", "")
        assert "i+++i++" not in normalized, \
            "Sequence point violation still present: i++ + i++"
        assert "j+j++" not in normalized, \
            "Sequence point violation still present: j + j++"


# --- New test content checks ---

class TestNewTestsContent:
    """Verify the three new tests contain the required C language features."""

    def test_irreducible_flow_has_goto(self):
        path = os.path.join(TESTS_DIR, "t_irreducible_flow.c")
        with open(path) as f:
            content = f.read()
        assert "goto" in content, \
            "t_irreducible_flow.c must use goto for irreducible control flow"

    def test_union_pun_uses_union(self):
        path = os.path.join(TESTS_DIR, "t_union_pun.c")
        with open(path) as f:
            content = f.read()
        assert "union" in content, \
            "t_union_pun.c must use union for type punning"
        assert "uint32_t" in content or "uint64_t" in content, \
            "t_union_pun.c must use fixed-width integer types"

    def test_restrict_qual_uses_restrict(self):
        path = os.path.join(TESTS_DIR, "t_restrict_qual.c")
        with open(path) as f:
            content = f.read()
        assert "restrict" in content, \
            "t_restrict_qual.c must use the restrict qualifier"


# --- Analysis report validation ---

class TestAnalysisReport:
    """Verify the analysis report structure and content."""

    def test_analysis_exists(self):
        assert os.path.exists(ANALYSIS_PATH), \
            "analysis.json not found at /app/analysis.json"

    def test_analysis_has_defects(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        assert "defects" in report, "analysis.json missing 'defects' key"
        assert len(report["defects"]) == 7, \
            f"Expected 7 defects, got {len(report['defects'])}"

    def test_analysis_defect_entries_have_fields(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        required_fields = {"file", "category", "description", "standard_ref", "fix_applied"}
        for defect in report["defects"]:
            for field in required_fields:
                assert field in defect, \
                    f"Defect entry for {defect.get('file', '?')} missing '{field}'"
            assert len(defect["description"]) > 20, \
                f"Description too short for {defect['file']}"
            assert len(defect["fix_applied"]) > 10, \
                f"fix_applied too short for {defect['file']}"

    def test_analysis_correct_categories(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        file_to_category = {d["file"]: d["category"] for d in report["defects"]}
        defective_files = set(file_to_category.keys())

        # Check all defective files are accounted for
        assert defective_files == ALL_DEFECTIVE_FILES, \
            f"Defect files mismatch. Expected {ALL_DEFECTIVE_FILES}, got {defective_files}"

        # Check wrong_expectation category
        for f in WRONG_EXPECTATION_FILES:
            assert file_to_category[f] == "wrong_expectation", \
                f"{f} should be 'wrong_expectation', got '{file_to_category[f]}'"

        # Check undefined_behavior category
        for f in UNDEFINED_BEHAVIOR_FILES:
            assert file_to_category[f] == "undefined_behavior", \
                f"{f} should be 'undefined_behavior', got '{file_to_category[f]}'"

        # Check implementation_defined category
        for f in IMPLEMENTATION_DEFINED_FILES:
            assert file_to_category[f] == "implementation_defined", \
                f"{f} should be 'implementation_defined', got '{file_to_category[f]}'"

    def test_analysis_category_counts(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        categories = [d["category"] for d in report["defects"]]
        assert categories.count("wrong_expectation") == 3, \
            f"Expected 3 wrong_expectation defects, got {categories.count('wrong_expectation')}"
        assert categories.count("undefined_behavior") == 3, \
            f"Expected 3 undefined_behavior defects, got {categories.count('undefined_behavior')}"
        assert categories.count("implementation_defined") == 1, \
            f"Expected 1 implementation_defined defect, got {categories.count('implementation_defined')}"

    def test_analysis_has_all_results(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        assert "all_results" in report, "analysis.json missing 'all_results' key"
        for test in ALL_TESTS:
            assert test in report["all_results"], \
                f"{test} missing from all_results"

    def test_analysis_results_have_all_configs(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        expected_keys = {"gcc_O0", "gcc_O2", "gcc_O3", "clang_O0", "clang_O2", "clang_O3"}
        for test, results in report["all_results"].items():
            for key in expected_keys:
                assert key in results, \
                    f"{test} missing result for {key}"

    def test_analysis_all_final_results_pass(self):
        with open(ANALYSIS_PATH) as f:
            report = json.load(f)
        for test, results in report["all_results"].items():
            for config, status in results.items():
                assert status == "pass", \
                    f"{test} {config} should be 'pass' in final results, got '{status}'"
