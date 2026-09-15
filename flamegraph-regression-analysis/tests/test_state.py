
import json
import os
import pytest


def load_report():
    path = "/app/output/report.json"
    assert os.path.exists(path), f"report.json not found at {path}"
    with open(path) as f:
        return json.load(f)


class TestSVGOutputs:
    """Verify flame graph SVG files are generated and valid."""

    def test_baseline_svg_exists(self):
        assert os.path.exists("/app/output/baseline.svg"), "baseline.svg not found"

    def test_regression_svg_exists(self):
        assert os.path.exists("/app/output/regression.svg"), "regression.svg not found"

    def test_diff_svg_exists(self):
        assert os.path.exists("/app/output/diff.svg"), "diff.svg not found"

    def test_baseline_svg_valid(self):
        with open("/app/output/baseline.svg") as f:
            content = f.read()
        assert "<svg" in content, "baseline.svg does not contain valid SVG markup"
        assert len(content) > 1000, "baseline.svg is suspiciously small"

    def test_regression_svg_valid(self):
        with open("/app/output/regression.svg") as f:
            content = f.read()
        assert "<svg" in content, "regression.svg does not contain valid SVG markup"
        assert len(content) > 1000, "regression.svg is suspiciously small"

    def test_diff_svg_valid(self):
        with open("/app/output/diff.svg") as f:
            content = f.read()
        assert "<svg" in content, "diff.svg does not contain valid SVG markup"
        assert len(content) > 1000, "diff.svg is suspiciously small"


class TestReportStructure:
    """Verify the report JSON has correct structure and required fields."""

    def test_report_exists(self):
        assert os.path.exists("/app/output/report.json")

    def test_report_valid_json(self):
        report = load_report()
        assert isinstance(report, dict)

    def test_required_fields_present(self):
        report = load_report()
        required = [
            "baseline_total_samples",
            "regression_total_samples",
            "exclusive_top5_baseline",
            "exclusive_top5_regression",
            "inclusive_top5_baseline",
            "inclusive_top5_regression",
            "new_functions",
            "removed_functions",
            "top_regressions",
            "top_improvements",
            "root_causes",
            "use_method",
        ]
        for field in required:
            assert field in report, f"Missing required field: {field}"


class TestTotalSamples:
    """Verify total sample counts are computed correctly."""

    def test_baseline_total(self):
        report = load_report()
        assert report["baseline_total_samples"] == 10000, (
            f"Expected 10000 baseline samples, got {report['baseline_total_samples']}"
        )

    def test_regression_total(self):
        report = load_report()
        assert report["regression_total_samples"] == 10000, (
            f"Expected 10000 regression samples, got {report['regression_total_samples']}"
        )


class TestExclusiveBaseline:
    """Verify exclusive (leaf/self) sample counts for baseline profile."""

    def test_top_function_is_btree_search(self):
        report = load_report()
        top5 = report["exclusive_top5_baseline"]
        assert len(top5) >= 3, "Need at least 3 entries in exclusive_top5_baseline"
        assert top5[0]["function"] == "btree_search", (
            f"Expected btree_search as top baseline exclusive, got {top5[0]['function']}"
        )

    def test_btree_search_count(self):
        report = load_report()
        top5 = report["exclusive_top5_baseline"]
        assert top5[0]["samples"] == 1300, (
            f"Expected btree_search=1300, got {top5[0]['samples']}"
        )

    def test_btree_search_percent(self):
        report = load_report()
        top5 = report["exclusive_top5_baseline"]
        assert abs(top5[0]["percent"] - 13.0) < 0.5, (
            f"Expected btree_search ~13.0%, got {top5[0]['percent']}"
        )

    def test_top5_contains_expected_functions(self):
        """The top 5 exclusive baseline should include these high-count functions."""
        report = load_report()
        top5_funcs = {e["function"] for e in report["exclusive_top5_baseline"]}
        # btree_search(1300), hmac_sha256(800), deflate_slow(800), fetch_rows(800)
        assert "btree_search" in top5_funcs
        # At least two of the three tied-at-800 should be present
        tied_800 = {"hmac_sha256", "deflate_slow", "fetch_rows"}
        assert len(top5_funcs & tied_800) >= 2, (
            f"Expected at least 2 of {tied_800} in top5, got {top5_funcs & tied_800}"
        )


class TestExclusiveRegression:
    """Verify exclusive sample counts for regression profile."""

    def test_top_function_is_regex_match(self):
        report = load_report()
        top5 = report["exclusive_top5_regression"]
        assert len(top5) >= 3, "Need at least 3 entries in exclusive_top5_regression"
        assert top5[0]["function"] == "regex_match", (
            f"Expected regex_match as top regression exclusive, got {top5[0]['function']}"
        )

    def test_regex_match_count(self):
        """regex_match appears in 3 stacks: 550+350+350=1250 exclusive samples."""
        report = load_report()
        top5 = report["exclusive_top5_regression"]
        assert top5[0]["samples"] == 1250, (
            f"Expected regex_match=1250 (sum of 3 leaf occurrences), got {top5[0]['samples']}"
        )

    def test_regex_match_percent(self):
        report = load_report()
        top5 = report["exclusive_top5_regression"]
        assert abs(top5[0]["percent"] - 12.5) < 0.5

    def test_second_is_btree_search(self):
        report = load_report()
        top5 = report["exclusive_top5_regression"]
        assert top5[1]["function"] == "btree_search"
        assert top5[1]["samples"] == 900

    def test_third_is_deep_copy(self):
        """deep_copy appears in 2 stacks: 450+200=650 exclusive samples."""
        report = load_report()
        top5 = report["exclusive_top5_regression"]
        assert top5[2]["function"] == "deep_copy"
        assert top5[2]["samples"] == 650


class TestInclusiveBaseline:
    """Verify inclusive (cumulative) sample counts for baseline."""

    def test_server_is_top(self):
        report = load_report()
        top5 = report["inclusive_top5_baseline"]
        assert top5[0]["function"] == "server"
        assert top5[0]["samples"] == 10000

    def test_main_loop_second(self):
        """main_loop inclusive = 10000 - 100 (signal_handler) = 9900."""
        report = load_report()
        top5 = report["inclusive_top5_baseline"]
        assert top5[1]["function"] == "main_loop"
        assert top5[1]["samples"] == 9900

    def test_handle_conn_third(self):
        """handle_conn inclusive = 10000 - 400(accept) - 900(gc) - 100(signal) = 8600."""
        report = load_report()
        top5 = report["inclusive_top5_baseline"]
        assert top5[2]["function"] == "handle_conn"
        assert top5[2]["samples"] == 8600

    def test_process_api_fourth(self):
        report = load_report()
        top5 = report["inclusive_top5_baseline"]
        assert top5[3]["function"] == "process_api"
        assert top5[3]["samples"] == 3600

    def test_query_db_fifth(self):
        report = load_report()
        top5 = report["inclusive_top5_baseline"]
        assert top5[4]["function"] == "query_db"
        assert top5[4]["samples"] == 3200


class TestInclusiveRegression:
    """Verify inclusive sample counts for regression."""

    def test_server_top(self):
        report = load_report()
        top5 = report["inclusive_top5_regression"]
        assert top5[0]["function"] == "server"
        assert top5[0]["samples"] == 10000

    def test_main_loop_second(self):
        """main_loop inclusive = 10000 - 50 (signal_handler) = 9950."""
        report = load_report()
        top5 = report["inclusive_top5_regression"]
        assert top5[1]["function"] == "main_loop"
        assert top5[1]["samples"] == 9950

    def test_handle_conn_third(self):
        """handle_conn inclusive = 10000 - 250(accept) - 1350(gc) - 50(signal) = 8350."""
        report = load_report()
        top5 = report["inclusive_top5_regression"]
        assert top5[2]["function"] == "handle_conn"
        assert top5[2]["samples"] == 8350

    def test_process_api_fourth(self):
        report = load_report()
        top5 = report["inclusive_top5_regression"]
        assert top5[3]["function"] == "process_api"
        assert top5[3]["samples"] == 3300

    def test_query_db_fifth(self):
        report = load_report()
        top5 = report["inclusive_top5_regression"]
        assert top5[4]["function"] == "query_db"
        assert top5[4]["samples"] == 2600


class TestNewAndRemovedFunctions:
    """Verify detection of new and removed function names."""

    def test_key_new_functions_detected(self):
        report = load_report()
        new_funcs = set(report["new_functions"])
        assert "regex_match" in new_funcs, "regex_match should be identified as new"
        assert "deep_copy" in new_funcs, "deep_copy should be identified as new"
        assert "fsync_data" in new_funcs, "fsync_data should be identified as new"

    def test_additional_new_functions(self):
        report = load_report()
        new_funcs = set(report["new_functions"])
        assert "validate_headers" in new_funcs
        assert "compile_pattern" in new_funcs
        assert "audit_log" in new_funcs
        assert "validate_schema" in new_funcs

    def test_no_removed_functions(self):
        """All baseline functions also appear in regression."""
        report = load_report()
        assert report["removed_functions"] == [], (
            f"Expected no removed functions, got {report['removed_functions']}"
        )

    def test_new_functions_count(self):
        """Exactly 11 functions are new in regression."""
        report = load_report()
        assert len(report["new_functions"]) == 11, (
            f"Expected 11 new functions, got {len(report['new_functions'])}: {report['new_functions']}"
        )


class TestRegressionDeltas:
    """Verify differential analysis identifies correct regression and improvement functions."""

    def test_top_regression_is_regex_match(self):
        report = load_report()
        regs = report["top_regressions"]
        assert len(regs) >= 3
        assert regs[0]["function"] == "regex_match"
        assert regs[0]["delta"] == 1250

    def test_second_regression_is_deep_copy(self):
        report = load_report()
        regs = report["top_regressions"]
        assert regs[1]["function"] == "deep_copy"
        assert regs[1]["delta"] == 650

    def test_third_regression_is_fsync_data(self):
        report = load_report()
        regs = report["top_regressions"]
        assert regs[2]["function"] == "fsync_data"
        assert regs[2]["delta"] == 500

    def test_top_improvement_is_btree_search(self):
        report = load_report()
        imps = report["top_improvements"]
        assert len(imps) >= 3
        assert imps[0]["function"] == "btree_search"
        assert imps[0]["delta"] == -400

    def test_improvements_have_negative_delta(self):
        report = load_report()
        for imp in report["top_improvements"]:
            assert imp["delta"] < 0, (
                f"Improvement {imp['function']} should have negative delta, got {imp['delta']}"
            )


class TestRootCauseAnalysis:
    """Verify that root causes identify the key performance issues."""

    def test_root_causes_exist(self):
        report = load_report()
        assert len(report["root_causes"]) >= 2, "Should identify at least 2 root causes"

    def test_regex_identified(self):
        report = load_report()
        causes_text = " ".join(report["root_causes"]).lower()
        assert any(
            kw in causes_text for kw in ["regex", "pattern", "validation"]
        ), "Root causes should mention regex/pattern/validation"

    def test_sync_io_identified(self):
        report = load_report()
        causes_text = " ".join(report["root_causes"]).lower()
        assert any(
            kw in causes_text for kw in ["fsync", "sync", "disk", "log"]
        ), "Root causes should mention synchronous disk I/O or logging"


class TestUSEMethod:
    """Verify USE Method analysis of system metrics."""

    def test_use_method_structure(self):
        report = load_report()
        use = report["use_method"]
        for resource in ["cpu", "memory", "disk", "network"]:
            assert resource in use, f"Missing USE method resource: {resource}"
            assert "utilization_percent" in use[resource]
            assert "saturated" in use[resource]

    def test_disk_saturated(self):
        """iostat shows aqu-sz > 2 and %util > 78% — disk is clearly saturated."""
        report = load_report()
        assert report["use_method"]["disk"]["saturated"] is True, (
            "Disk should be identified as saturated (aqu-sz > 1, %util > 78%)"
        )

    def test_disk_utilization_range(self):
        """Average disk %util across 3 samples: (78.5+85.2+82.0)/3 ≈ 81.9%."""
        report = load_report()
        util = report["use_method"]["disk"]["utilization_percent"]
        assert 70 < util < 95, f"Expected disk utilization ~82%, got {util}"

    def test_memory_not_saturated(self):
        """No swap activity (si=0, so=0) — memory is not saturated."""
        report = load_report()
        assert report["use_method"]["memory"]["saturated"] is False, (
            "Memory should not be saturated (no swap activity)"
        )

    def test_cpu_utilization_range(self):
        """Average CPU: us+sy ≈ (62+65+60+64+63)/5 + (12+11+13+12+12)/5 ≈ 74.8%."""
        report = load_report()
        util = report["use_method"]["cpu"]["utilization_percent"]
        assert 60 < util < 90, f"Expected CPU utilization ~75%, got {util}"
