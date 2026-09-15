
import subprocess
import json
import functools


@functools.lru_cache(maxsize=1)
def run_expression_evaluator():
    """Install deps and run the expression evaluator test suite."""
    install = subprocess.run(
        ["npm", "install", "--legacy-peer-deps"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert install.returncode == 0, f"npm install failed: {install.stderr}"

    result = subprocess.run(
        ["npx", "tsx", "run_tests.ts"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Test runner failed with exit code {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    return tuple(json.loads(result.stdout))


@functools.lru_cache(maxsize=1)
def run_inheritance_resolver():
    """Run the inheritance resolver against test dataset."""
    result = subprocess.run(
        ["npx", "tsx", "resolve.ts", "spec/inheritance_tests.json"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Resolve runner failed with exit code {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    return tuple(json.loads(result.stdout))


@functools.lru_cache(maxsize=1)
def run_validation_engine():
    """Run the validation rule engine against test contexts."""
    result = subprocess.run(
        ["npx", "tsx", "validate.ts", "spec/test_contexts.json"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Validation runner failed with exit code {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    return tuple(json.loads(result.stdout))


def get_report(reports, file_id):
    """Get validation report for a specific file context."""
    for r in reports:
        if r["file_id"] == file_id:
            return r
    raise AssertionError(f"No report found for file_id: {file_id}")


class TestExpressionEvaluator:
    """Verify the BIDS expression language evaluator."""

    def test_all_expressions_pass(self):
        """Every expression test case must produce the correct result."""
        results = list(run_expression_evaluator())
        failures = [r for r in results if not r["passed"]]
        assert len(failures) == 0, (
            f"{len(failures)} expression test(s) failed:\n"
            + "\n".join(
                f"  {f['expression']}: expected {f['expected']!r}, got {f['actual']!r}"
                + (f" (error: {f['error']})" if f.get("error") else "")
                for f in failures
            )
        )

    def test_minimum_test_count(self):
        """Ensure a minimum number of tests were actually executed."""
        results = list(run_expression_evaluator())
        assert len(results) >= 75, (
            f"Expected at least 75 expression tests, but only {len(results)} ran"
        )

    def test_null_propagation(self):
        """Null propagation must follow the specification."""
        results = list(run_expression_evaluator())
        null_tests = [r for r in results if "null" in r["expression"].lower()]
        null_failures = [r for r in null_tests if not r["passed"]]
        assert len(null_failures) == 0, (
            f"{len(null_failures)} null propagation test(s) failed:\n"
            + "\n".join(
                f"  {f['expression']}: expected {f['expected']!r}, got {f['actual']!r}"
                + (f" (error: {f['error']})" if f.get("error") else "")
                for f in null_failures
            )
        )

    def test_arithmetic_operations(self):
        """All arithmetic operators must produce correct results."""
        results = list(run_expression_evaluator())
        arith_exprs = {"1 + 2", "1 - 2", "3 * 4", "3 / 2", "3 % 2"}
        arith_results = [r for r in results if r["expression"] in arith_exprs]
        arith_failures = [r for r in arith_results if not r["passed"]]
        assert len(arith_failures) == 0, (
            f"Arithmetic test(s) failed:\n"
            + "\n".join(
                f"  {f['expression']}: expected {f['expected']!r}, got {f['actual']!r}"
                for f in arith_failures
            )
        )

    def test_builtin_functions(self):
        """All built-in function calls must produce correct results."""
        results = list(run_expression_evaluator())
        func_tests = [
            r
            for r in results
            if "(" in r["expression"] and r["expression"][0].isalpha()
        ]
        func_failures = [r for r in func_tests if not r["passed"]]
        assert len(func_failures) == 0, (
            f"{len(func_failures)} built-in function test(s) failed:\n"
            + "\n".join(
                f"  {f['expression']}: expected {f['expected']!r}, got {f['actual']!r}"
                + (f" (error: {f['error']})" if f.get("error") else "")
                for f in func_failures
            )
        )

    def test_sorted_regression(self):
        """sorted() must not use lexical comparison for numeric arrays."""
        results = list(run_expression_evaluator())
        sorted_test = next(
            (
                r
                for r in results
                if r["expression"] == "sorted([9, 81, 729, 6561])"
            ),
            None,
        )
        assert sorted_test is not None, "Missing sorted regression test case"
        assert sorted_test["passed"], (
            f"sorted([9, 81, 729, 6561]) should be [9, 81, 729, 6561], "
            f"got {sorted_test['actual']!r}"
        )

    def test_comparison_operators(self):
        """Equality and inequality operators must work with null and values."""
        results = list(run_expression_evaluator())
        cmp_exprs = {
            "null == false",
            "null == true",
            "null != false",
            "null != true",
            "null != 1.5",
            "null == null",
            "null == 1",
        }
        cmp_results = [r for r in results if r["expression"] in cmp_exprs]
        cmp_failures = [r for r in cmp_results if not r["passed"]]
        assert len(cmp_failures) == 0, (
            f"Comparison test(s) failed:\n"
            + "\n".join(
                f"  {f['expression']}: expected {f['expected']!r}, got {f['actual']!r}"
                + (f" (error: {f['error']})" if f.get("error") else "")
                for f in cmp_failures
            )
        )

    def test_indexing(self):
        """Array and string indexing must work correctly."""
        results = list(run_expression_evaluator())
        idx_exprs = {"[3, 2, 1][0]", '"string"[0]', "null[0]"}
        idx_results = [r for r in results if r["expression"] in idx_exprs]
        idx_failures = [r for r in idx_results if not r["passed"]]
        assert len(idx_failures) == 0, (
            f"Indexing test(s) failed:\n"
            + "\n".join(
                f"  {f['expression']}: expected {f['expected']!r}, got {f['actual']!r}"
                + (f" (error: {f['error']})" if f.get("error") else "")
                for f in idx_failures
            )
        )


class TestInheritanceResolver:
    """Verify the BIDS sidecar inheritance resolver."""

    def test_all_inheritance_pass(self):
        """Every inheritance test case must resolve correctly."""
        results = list(run_inheritance_resolver())
        failures = [r for r in results if not r["passed"]]
        assert len(failures) == 0, (
            f"{len(failures)} inheritance test(s) failed:\n"
            + "\n".join(
                f"  {f['file_id']}:\n"
                f"    resolved:  {f['resolved_metadata']}\n"
                f"    expected:  {f['expected_metadata']}\n"
                f"    sidecars:  {f['applied_sidecars']}\n"
                f"    expected:  {f['expected_sidecars']}"
                for f in failures
            )
        )

    def test_minimum_test_count(self):
        """Ensure a minimum number of inheritance tests were executed."""
        results = list(run_inheritance_resolver())
        assert len(results) >= 5, (
            f"Expected at least 5 inheritance tests, got {len(results)}"
        )

    def test_multi_level_sidecars(self):
        """A file deep in the tree should inherit from all ancestor directories."""
        results = list(run_inheritance_resolver())
        report = next(
            (r for r in results if "run-01" in r["file_id"]), None
        )
        assert report is not None, "Missing multi-level inheritance test"
        assert report["passed"], (
            f"Multi-level inheritance test failed:\n"
            f"  resolved:  {report['resolved_metadata']}\n"
            f"  expected:  {report['expected_metadata']}\n"
            f"  sidecars:  {report['applied_sidecars']}"
        )
        assert len(report["applied_sidecars"]) == 4, (
            f"Expected 4 applied sidecars from root to deepest, "
            f"got {len(report['applied_sidecars'])}: {report['applied_sidecars']}"
        )

    def test_override_semantics(self):
        """Deeper sidecars must override values from shallower ones."""
        results = list(run_inheritance_resolver())
        report = next(
            (r for r in results if "sub-02" in r["file_id"]), None
        )
        assert report is not None, "Missing override semantics test"
        assert report["passed"], (
            f"Override test failed:\n"
            f"  resolved:  {report['resolved_metadata']}\n"
            f"  expected:  {report['expected_metadata']}"
        )
        assert report["resolved_metadata"].get("MagneticFieldStrength") == 7, (
            f"MagneticFieldStrength should be 7 (overridden by deeper sidecar), "
            f"got {report['resolved_metadata'].get('MagneticFieldStrength')}"
        )

    def test_suffix_filtering(self):
        """Sidecars must only match files with the same suffix."""
        results = list(run_inheritance_resolver())
        report = next(
            (r for r in results if "events" in r["file_id"]), None
        )
        assert report is not None, "Missing suffix filtering test"
        assert report["passed"], (
            f"Suffix filtering test failed: {report['resolved_metadata']}"
        )
        assert len(report["applied_sidecars"]) == 0, (
            f"Events file should have no bold sidecars applied: "
            f"{report['applied_sidecars']}"
        )

    def test_entity_filtering(self):
        """Sidecars with non-matching entity values must be excluded."""
        results = list(run_inheritance_resolver())
        report = next(
            (r for r in results if "auditory" in r["file_id"]), None
        )
        assert report is not None, "Missing entity filtering test"
        assert report["passed"], (
            f"Entity filtering test failed:\n"
            f"  resolved:  {report['resolved_metadata']}\n"
            f"  expected:  {report['expected_metadata']}"
        )
        assert "TaskName" not in report["resolved_metadata"], (
            f"TaskName from task-rest sidecar should NOT apply to "
            f"task-auditory file"
        )

    def test_compound_extension(self):
        """Files with compound extensions (.nii.gz) must resolve correctly."""
        results = list(run_inheritance_resolver())
        report = next(
            (r for r in results if "T1w" in r["file_id"]), None
        )
        assert report is not None, "Missing compound extension test"
        assert report["passed"], (
            f"Compound extension test failed:\n"
            f"  resolved:  {report['resolved_metadata']}\n"
            f"  expected:  {report['expected_metadata']}"
        )
        assert len(report["applied_sidecars"]) == 1, (
            f"T1w file should match exactly 1 sidecar (root T1w.json), "
            f"got {report['applied_sidecars']}"
        )


class TestValidationRuleEngine:
    """Verify the BIDS validation rule engine."""

    def test_validation_runner_executes(self):
        """The validation runner must execute without crashing."""
        reports = list(run_validation_engine())
        assert len(reports) == 7, (
            f"Expected 7 validation reports, got {len(reports)}"
        )

    def test_func_bold_valid_passes(self):
        """A fully valid BOLD file should pass with no issues."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_valid")
        assert report["passed"] is True, (
            f"func_bold_valid should pass but got issues: {report['issues']}"
        )
        assert len(report["issues"]) == 0, (
            f"func_bold_valid should have no issues: {report['issues']}"
        )

    def test_func_bold_valid_matched_rules(self):
        """A valid BOLD file with task and run entities should match all applicable rules."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_valid")
        matched = set(report["matched_rules"])
        expected = {
            "REPETITION_TIME_MUST_DEFINE",
            "TASK_NAME_VALID",
            "ECHO_TIME_RANGE",
            "SLICE_TIMING_LENGTH",
            "PHASE_ENCODING_DIRECTION",
            "UNIQUE_RUNS",
        }
        assert matched == expected, (
            f"func_bold_valid matched rules mismatch.\n"
            f"  Expected: {expected}\n  Got: {matched}\n"
            f"  Missing: {expected - matched}\n  Extra: {matched - expected}"
        )

    def test_func_bold_missing_rt_fails(self):
        """A BOLD file missing RepetitionTime should fail with an error."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_missing_rt")
        assert report["passed"] is False
        errors = [i for i in report["issues"] if i["level"] == "error"]
        assert len(errors) >= 1, "Missing RepetitionTime should produce at least one error"
        error_rules = {e["rule_id"] for e in errors}
        assert "REPETITION_TIME_MUST_DEFINE" in error_rules

    def test_func_bold_missing_rt_warnings(self):
        """Missing optional sidecar fields should produce warnings, not errors."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_missing_rt")
        warnings = [i for i in report["issues"] if i["level"] == "warning"]
        warning_rules = {w["rule_id"] for w in warnings}
        assert "SLICE_TIMING_LENGTH" in warning_rules, (
            "Missing SliceTiming should produce a warning"
        )
        assert "PHASE_ENCODING_DIRECTION" in warning_rules, (
            "Missing PhaseEncodingDirection should produce a warning"
        )

    def test_events_valid_passes(self):
        """An events file with required columns should pass."""
        reports = list(run_validation_engine())
        report = get_report(reports, "events_valid")
        assert report["passed"] is True
        assert len(report["issues"]) == 0

    def test_events_valid_matched_rules(self):
        """An events file should match TASK_NAME_VALID and EVENTS_COLUMNS."""
        reports = list(run_validation_engine())
        report = get_report(reports, "events_valid")
        matched = set(report["matched_rules"])
        assert "EVENTS_COLUMNS" in matched, "events file should match EVENTS_COLUMNS rule"
        assert "TASK_NAME_VALID" in matched, "events file with task entity should match TASK_NAME_VALID"

    def test_events_missing_columns_fails(self):
        """An events file missing onset and duration columns should fail."""
        reports = list(run_validation_engine())
        report = get_report(reports, "events_missing_columns")
        assert report["passed"] is False
        errors = [i for i in report["issues"] if i["level"] == "error"]
        assert len(errors) == 2, (
            f"Expected 2 column errors (onset, duration), got {len(errors)}: {errors}"
        )
        error_rules = {e["rule_id"] for e in errors}
        assert error_rules == {"EVENTS_COLUMNS"}

    def test_anat_t1w_passes(self):
        """An anat T1w file should pass (no task/run entity required rules apply)."""
        reports = list(run_validation_engine())
        report = get_report(reports, "anat_t1w")
        assert report["passed"] is True
        assert len(report["issues"]) == 0

    def test_anat_t1w_matched_rules(self):
        """Anat T1w should only match ECHO_TIME_RANGE (no task/run entities)."""
        reports = list(run_validation_engine())
        report = get_report(reports, "anat_t1w")
        matched = set(report["matched_rules"])
        assert "ECHO_TIME_RANGE" in matched
        assert "TASK_NAME_VALID" not in matched, (
            "TASK_NAME_VALID requires task entity; anat_t1w has no task entity"
        )
        assert "UNIQUE_RUNS" not in matched, (
            "UNIQUE_RUNS requires run entity; anat_t1w has no run entity"
        )

    def test_bad_taskname_passes_with_warnings(self):
        """A file with bad TaskName should pass (only warnings, no errors)."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_bad_taskname")
        assert report["passed"] is True, (
            f"func_bold_bad_taskname should pass (warnings only) but failed.\n"
            f"Issues: {report['issues']}"
        )
        warnings = [i for i in report["issues"] if i["level"] == "warning"]
        assert len(warnings) >= 1, "Bad TaskName should produce at least one warning"

    def test_bad_taskname_has_taskname_warning(self):
        """TaskName 'my-rest' should trigger the alphanumeric pattern warning."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_bad_taskname")
        taskname_warnings = [
            i for i in report["issues"]
            if i["rule_id"] == "TASK_NAME_VALID" and i["level"] == "warning"
        ]
        assert len(taskname_warnings) == 1, (
            f"Expected 1 TASK_NAME_VALID warning, got {len(taskname_warnings)}"
        )

    def test_bad_echotime_fails(self):
        """EchoTime > 1 and empty SliceTiming should produce errors."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_bad_echotime")
        assert report["passed"] is False
        errors = [i for i in report["issues"] if i["level"] == "error"]
        error_rules = {e["rule_id"] for e in errors}
        assert "ECHO_TIME_RANGE" in error_rules, (
            "EchoTime=1.5 should trigger ECHO_TIME_RANGE error"
        )
        assert "SLICE_TIMING_LENGTH" in error_rules, (
            "Empty SliceTiming should trigger SLICE_TIMING_LENGTH error"
        )

    def test_bad_echotime_no_false_warnings(self):
        """Checks with depends_on should skip when their dependency fails."""
        reports = list(run_validation_engine())
        report = get_report(reports, "func_bold_missing_rt")
        slice_issues = [
            i for i in report["issues"] if i["rule_id"] == "SLICE_TIMING_LENGTH"
        ]
        assert len(slice_issues) == 1, (
            f"SLICE_TIMING_LENGTH should produce exactly 1 issue (the warning), "
            f"but got {len(slice_issues)}: {slice_issues}"
        )
        assert slice_issues[0]["level"] == "warning", (
            "SLICE_TIMING_LENGTH issue for missing field should be a warning"
        )
        assert slice_issues[0]["check_index"] == 0, (
            "The SLICE_TIMING_LENGTH warning should be from check 0 (null check), "
            f"got check_index={slice_issues[0]['check_index']}"
        )
