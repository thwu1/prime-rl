"""
Tests for the FileCheck conformance audit task with lit integration.

Verifies:
  1. Fixed filecheck.py produces correct outcomes for all manifest test cases
  2. audit.json exists with correct structure and root-cause classifications
  3. lit test suite exists and all tests pass via lit
  4. spec_evaluation.json has correct structure covering 8+ feature areas
  5. spec_probes/ contains at least 5 passing probe test pairs
  6. edge_cases/ contains at least 3 passing test pairs
"""

import subprocess
import pytest
import json
import os
import glob


TOOL = "/app/filecheck.py"
TESTS = "/app/test_inputs"


def run_filecheck(check_file, input_file, extra_args=None):
    """Run the filecheck tool and return (exit_code, stdout, stderr)."""
    cmd = ["python3", TOOL, check_file, "--input-file", input_file]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


# =====================================================================
# Tests that should pass (basic functionality)
# =====================================================================

class TestBasicFunctionality:
    """Tests that verify basic directives work correctly."""

    def test_basic_check_label_vars(self):
        """CHECK, CHECK-NEXT, CHECK-LABEL, CHECK-SAME, variables."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/basic.check", f"{TESTS}/basic.input")
        assert rc == 0, f"Basic test failed: {stderr}"

    def test_custom_prefix(self):
        """--check-prefix with MYCHECK prefix."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/custom_prefix.check", f"{TESTS}/custom_prefix.input",
            extra_args=["--check-prefix=MYCHECK"])
        assert rc == 0, f"Custom prefix failed: {stderr}"

    def test_full_lines(self):
        """--match-full-lines requires patterns to match entire line."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/full_lines.check", f"{TESTS}/full_lines.input",
            extra_args=["--match-full-lines"])
        assert rc == 0, f"Full lines test failed: {stderr}"


# =====================================================================
# Bug-fix validation
# =====================================================================

class TestBugFixes:
    """Tests that fail with the buggy code but must pass after fixes."""

    def test_comment_prefix_support(self):
        """Bug 1: Parser must find directives after // and # prefixes."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/comment_prefix.check",
            f"{TESTS}/comment_prefix.input")
        assert rc == 0, (
            f"Comment prefix support broken -- parser likely only "
            f"recognizes ';' prefix. stderr: {stderr}")

    def test_check_not_bounded_by_next_match(self):
        """Bug 2: CHECK-NOT must only scan up to the next positive match."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/check_not_bounded.check",
            f"{TESTS}/check_not_bounded.input")
        assert rc == 0, (
            f"CHECK-NOT scoped incorrectly -- scanning past the "
            f"next positive match. stderr: {stderr}")

    def test_dag_backtracking(self):
        """Bug 3: CHECK-DAG must backtrack when greedy first-fit fails."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/dag_backtrack.check",
            f"{TESTS}/dag_backtrack.input")
        assert rc == 0, (
            f"CHECK-DAG greedy assignment failed -- backtracking "
            f"required. stderr: {stderr}")

    def test_multi_prefix_merged(self):
        """Bug 4: --check-prefixes must merge by source line order."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/multi_prefix.check",
            f"{TESTS}/multi_prefix.input",
            extra_args=["--check-prefixes=CHECK,ALT"])
        assert rc == 0, (
            f"Multi-prefix interleaving broken -- prefixes likely "
            f"run independently. stderr: {stderr}")

    def test_count_repeat_consecutive(self):
        """Bug 5: CHECK-COUNT-N must match N consecutive lines."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/count_repeat.check",
            f"{TESTS}/count_repeat.input")
        assert rc == 0, (
            f"CHECK-COUNT-3 failed -- likely treated as single CHECK "
            f"instead of matching 3 consecutive lines. stderr: {stderr}")

    def test_interacting_bugs(self):
        """Bugs 2+5: CHECK-NOT scope + CHECK-COUNT interaction."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/interacting.check",
            f"{TESTS}/interacting.input")
        assert rc == 0, (
            f"Interacting test failed -- requires both CHECK-NOT scope "
            f"fix and CHECK-COUNT-N fix. stderr: {stderr}")


# =====================================================================
# Wrong pattern (red herring) - must be fixed in check file
# =====================================================================

class TestPatternCorrections:
    """Test cases where CHECK patterns needed correction, not tool fixes."""

    def test_wrong_pattern_corrected(self):
        """Wrong CHECK pattern must be fixed so test passes."""
        rc, _, stderr = run_filecheck(
            f"{TESTS}/wrong_pattern.check",
            f"{TESTS}/wrong_pattern.input")
        assert rc == 0, (
            f"wrong_pattern test still failing -- CHECK patterns need "
            f"correction (this is NOT a tool bug). stderr: {stderr}")


# =====================================================================
# Negative tests (must correctly reject invalid input)
# =====================================================================

class TestNegativeCases:
    """Tests where the tool must correctly report failure."""

    def test_pattern_not_found_rejects(self):
        """CHECK-NEXT for a nonexistent pattern must fail."""
        rc, _, _ = run_filecheck(
            f"{TESTS}/negative_fail.check",
            f"{TESTS}/negative_fail.input")
        assert rc != 0, "Should reject when CHECK-NEXT pattern not found"

    def test_check_not_violated_rejects(self):
        """CHECK-NOT must fail when forbidden pattern appears in scope."""
        rc, _, _ = run_filecheck(
            f"{TESTS}/not_violated_fail.check",
            f"{TESTS}/not_violated_fail.input")
        assert rc != 0, (
            "Should reject when CHECK-NOT pattern found between "
            "positive matches")

    def test_count_insufficient_rejects(self):
        """CHECK-COUNT-3 must fail when only 2 consecutive matches exist."""
        rc, _, _ = run_filecheck(
            f"{TESTS}/count_fail.check",
            f"{TESTS}/count_fail.input")
        assert rc != 0, (
            "CHECK-COUNT-3 should fail with only 2 consecutive matches "
            "-- tool may be treating COUNT-N as plain CHECK")


# =====================================================================
# Audit report validation
# =====================================================================

class TestAuditReport:
    """Verify the structured audit report."""

    def test_audit_exists(self):
        """audit.json must exist."""
        assert os.path.exists("/app/audit.json"), \
            "audit.json not found at /app/audit.json"

    def test_audit_valid_json(self):
        """audit.json must be valid JSON."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        assert isinstance(data, list), "audit.json must be a JSON array"

    def test_audit_has_required_fields(self):
        """Each audit entry must have test_case, root_cause, description."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        assert len(data) >= 6, (
            f"Audit should have at least 6 entries (5 impl bugs + "
            f"wrong pattern), got {len(data)}")
        for entry in data:
            assert "test_case" in entry, \
                f"Missing 'test_case' field in audit entry: {entry}"
            assert "root_cause" in entry, \
                f"Missing 'root_cause' field in audit entry: {entry}"
            assert "description" in entry, \
                f"Missing 'description' field in audit entry: {entry}"
            assert entry["root_cause"] in (
                "implementation_bug", "wrong_pattern"), \
                f"root_cause must be 'implementation_bug' or " \
                f"'wrong_pattern', got '{entry['root_cause']}'"

    def test_audit_identifies_wrong_pattern(self):
        """Audit must identify wrong_pattern as a pattern issue."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        wp = [e for e in data if e.get("test_case") == "wrong_pattern"]
        assert len(wp) > 0, \
            "Audit must include an entry for 'wrong_pattern'"
        assert wp[0]["root_cause"] == "wrong_pattern", (
            f"wrong_pattern root_cause should be 'wrong_pattern' "
            f"(not an implementation bug), got '{wp[0]['root_cause']}'")

    def test_audit_identifies_impl_bugs(self):
        """Audit must identify implementation bugs for tool-related failures."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        impl_bugs = [e for e in data
                     if e.get("root_cause") == "implementation_bug"]
        impl_names = {e["test_case"] for e in impl_bugs}
        expected_bugs = {
            "comment_prefix", "check_not_bounded", "dag_backtrack",
            "multi_prefix", "count_repeat"
        }
        missing = expected_bugs - impl_names
        assert not missing, (
            f"Audit is missing implementation_bug entries for: {missing}")


# =====================================================================
# lit test suite validation
# =====================================================================

class TestLitSuite:
    """Verify the lit-based conformance test suite."""

    def test_lit_cfg_exists(self):
        """lit.cfg.py must exist in /app/lit_suite/."""
        assert os.path.exists("/app/lit_suite/lit.cfg.py"), \
            "lit.cfg.py not found at /app/lit_suite/lit.cfg.py"

    def test_lit_cfg_valid_python(self):
        """lit.cfg.py must be syntactically valid Python."""
        import ast
        with open("/app/lit_suite/lit.cfg.py") as f:
            content = f.read()
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"lit.cfg.py has syntax error: {e}")

    def test_lit_test_files_exist(self):
        """At least 13 .test files must exist (one per manifest case)."""
        test_files = glob.glob("/app/lit_suite/*.test")
        assert len(test_files) >= 13, (
            f"Expected at least 13 .test files, found {len(test_files)}: "
            f"{[os.path.basename(f) for f in test_files]}")

    def test_lit_test_files_have_run_lines(self):
        """Each .test file must contain at least one RUN: directive."""
        test_files = glob.glob("/app/lit_suite/*.test")
        assert len(test_files) > 0, "No .test files found"
        for tf in test_files:
            with open(tf) as f:
                content = f.read()
            assert "RUN:" in content, (
                f"{os.path.basename(tf)} has no RUN: directive")

    def test_lit_negative_tests_use_not(self):
        """Tests for expected-failure manifest cases must use lit's not."""
        with open("/app/manifest.json") as f:
            manifest = json.load(f)
        fail_cases = {tc["name"] for tc in manifest["test_cases"]
                      if tc["expected"] == "fail"}
        test_files = glob.glob("/app/lit_suite/*.test")
        for tf in test_files:
            basename = os.path.splitext(os.path.basename(tf))[0]
            if basename in fail_cases:
                with open(tf) as f:
                    content = f.read()
                assert "not " in content.lower() or "not\t" in content.lower(), (
                    f"{os.path.basename(tf)} is an expected-failure test "
                    f"but doesn't use lit's 'not' command")

    def test_lit_suite_all_pass(self):
        """Running lit on the suite must report all tests passing."""
        result = subprocess.run(
            ["lit", "/app/lit_suite", "-v",
             "--no-progress-bar"],
            capture_output=True, text=True, timeout=120)
        combined = result.stdout + "\n" + result.stderr
        assert result.returncode == 0, (
            f"lit suite failed (exit {result.returncode}):\n{combined}")
        # Verify all 13 tests were discovered and passed
        pass_count = combined.count("PASS:")
        assert pass_count >= 13, (
            f"Expected at least 13 PASS results from lit, got {pass_count}. "
            f"Output:\n{combined}")


# =====================================================================
# Specification evaluation validation
# =====================================================================

class TestSpecEvaluation:
    """Verify the specification compliance evaluation."""

    def test_spec_eval_exists(self):
        """spec_evaluation.json must exist."""
        assert os.path.exists("/app/spec_evaluation.json"), \
            "spec_evaluation.json not found at /app/spec_evaluation.json"

    def test_spec_eval_valid_json(self):
        """spec_evaluation.json must be valid JSON array."""
        with open("/app/spec_evaluation.json") as f:
            data = json.load(f)
        assert isinstance(data, list), \
            "spec_evaluation.json must be a JSON array"

    def test_spec_eval_coverage(self):
        """Must cover at least 8 distinct feature areas."""
        with open("/app/spec_evaluation.json") as f:
            data = json.load(f)
        assert len(data) >= 8, (
            f"Expected at least 8 feature areas, got {len(data)}")
        features = [e.get("feature", "") for e in data]
        unique_features = set(f.lower().strip() for f in features)
        assert len(unique_features) >= 8, (
            f"Expected 8 unique features, got {len(unique_features)}: "
            f"{unique_features}")

    def test_spec_eval_structure(self):
        """Each entry must have required fields with valid values."""
        with open("/app/spec_evaluation.json") as f:
            data = json.load(f)
        valid_compliance = {"full", "partial", "none"}
        for entry in data:
            assert "feature" in entry, \
                f"Missing 'feature' field: {entry}"
            assert "compliance" in entry, \
                f"Missing 'compliance' in {entry.get('feature', '?')}"
            assert entry["compliance"] in valid_compliance, (
                f"Invalid compliance '{entry['compliance']}' for "
                f"'{entry.get('feature', '?')}'. "
                f"Must be one of {valid_compliance}")
            assert "tested_behaviors" in entry, (
                f"Missing 'tested_behaviors' in "
                f"'{entry.get('feature', '?')}'")
            assert isinstance(entry["tested_behaviors"], list), (
                f"'tested_behaviors' must be a list in "
                f"'{entry.get('feature', '?')}'")
            assert len(entry["tested_behaviors"]) > 0, (
                f"'tested_behaviors' is empty in "
                f"'{entry.get('feature', '?')}'")
            assert "untested_behaviors" in entry, (
                f"Missing 'untested_behaviors' in "
                f"'{entry.get('feature', '?')}'")
            assert isinstance(entry["untested_behaviors"], list), (
                f"'untested_behaviors' must be a list in "
                f"'{entry.get('feature', '?')}'")
            assert "risk_assessment" in entry, (
                f"Missing 'risk_assessment' in "
                f"'{entry.get('feature', '?')}'")
            assert isinstance(entry["risk_assessment"], str), (
                f"'risk_assessment' must be a string in "
                f"'{entry.get('feature', '?')}'")
            assert len(entry["risk_assessment"].strip()) > 0, (
                f"'risk_assessment' is empty in "
                f"'{entry.get('feature', '?')}'")


# =====================================================================
# Specification probe tests validation
# =====================================================================

class TestSpecProbes:
    """Verify specification boundary probe tests."""

    def test_spec_probes_directory_exists(self):
        """spec_probes/ directory must exist."""
        assert os.path.isdir("/app/spec_probes"), \
            "spec_probes directory not found at /app/spec_probes"

    def test_at_least_five_probes(self):
        """At least 5 probe test pairs must exist."""
        probe_dir = "/app/spec_probes"
        check_files = glob.glob(f"{probe_dir}/*.check")
        assert len(check_files) >= 5, (
            f"Need at least 5 probe pairs, found {len(check_files)}")
        for cf in check_files:
            base = cf.rsplit('.check', 1)[0]
            assert os.path.exists(f"{base}.input"), \
                f"Missing .input file for {os.path.basename(cf)}"

    def test_spec_probes_pass(self):
        """All spec probes must pass with the fixed implementation."""
        probe_dir = "/app/spec_probes"
        check_files = glob.glob(f"{probe_dir}/*.check")
        assert len(check_files) >= 5, "Not enough spec probes"
        for cf in check_files:
            base = cf.rsplit('.check', 1)[0]
            input_file = f"{base}.input"
            rc, _, stderr = run_filecheck(cf, input_file)
            assert rc == 0, (
                f"Spec probe {os.path.basename(cf)} failed: {stderr}")

    def test_spec_probes_distinct_features(self):
        """Probes must test at least 3 distinct directive types."""
        probe_dir = "/app/spec_probes"
        check_files = glob.glob(f"{probe_dir}/*.check")
        assert len(check_files) >= 5, "Not enough spec probes"
        seen_directives = set()
        for cf in check_files:
            with open(cf) as f:
                content = f.read()
            for keyword in ["CHECK-NEXT", "CHECK-NOT", "CHECK-DAG",
                            "CHECK-LABEL", "CHECK-SAME", "CHECK-COUNT"]:
                if keyword in content:
                    seen_directives.add(keyword)
            if "CHECK:" in content or "CHECK " in content:
                seen_directives.add("CHECK")
        assert len(seen_directives) >= 3, (
            f"Spec probes should exercise at least 3 distinct directive "
            f"types, found only: {seen_directives}")


# =====================================================================
# Edge case tests validation
# =====================================================================

class TestEdgeCases:
    """Verify edge case test files exist and pass."""

    def test_edge_cases_directory_exists(self):
        """edge_cases/ directory must exist."""
        assert os.path.isdir("/app/edge_cases"), \
            "edge_cases directory not found at /app/edge_cases"

    def test_at_least_three_edge_cases(self):
        """At least 3 edge case test pairs must exist."""
        edge_dir = "/app/edge_cases"
        check_files = glob.glob(f"{edge_dir}/*.check")
        assert len(check_files) >= 3, (
            f"Need at least 3 edge case pairs, found {len(check_files)}")
        for cf in check_files:
            base = cf.rsplit('.check', 1)[0]
            assert os.path.exists(f"{base}.input"), \
                f"Missing .input file for {os.path.basename(cf)}"

    def test_edge_cases_pass(self):
        """All edge cases must pass with the fixed implementation."""
        edge_dir = "/app/edge_cases"
        check_files = glob.glob(f"{edge_dir}/*.check")
        assert len(check_files) >= 3, "Not enough edge cases"
        for cf in check_files:
            base = cf.rsplit('.check', 1)[0]
            input_file = f"{base}.input"
            rc, _, stderr = run_filecheck(cf, input_file)
            assert rc == 0, (
                f"Edge case {os.path.basename(cf)} failed: {stderr}")

    def test_edge_cases_exercise_distinct_features(self):
        """Edge cases should test different FileCheck features.
        Check that the .check files use at least 2 distinct directive types
        across all edge cases (not all plain CHECK)."""
        edge_dir = "/app/edge_cases"
        check_files = glob.glob(f"{edge_dir}/*.check")
        assert len(check_files) >= 3, "Not enough edge cases"
        seen_directives = set()
        for cf in check_files:
            with open(cf) as f:
                content = f.read()
            for keyword in ["CHECK-NEXT", "CHECK-NOT", "CHECK-DAG",
                            "CHECK-LABEL", "CHECK-SAME", "CHECK-COUNT"]:
                if keyword in content:
                    seen_directives.add(keyword)
            if "CHECK:" in content or "CHECK " in content:
                seen_directives.add("CHECK")
        assert len(seen_directives) >= 2, (
            f"Edge cases should exercise at least 2 distinct directive "
            f"types, found only: {seen_directives}")
