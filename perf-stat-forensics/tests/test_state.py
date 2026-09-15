
import json
import os
import pytest
import subprocess


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the analyzer before all tests."""
    result = subprocess.run(
        ["python3", "/app/perf_analyzer.py"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert result.returncode == 0, f"Analyzer failed with stderr: {result.stderr}\nstdout: {result.stdout}"


@pytest.fixture
def report():
    with open("/app/analysis_report.json") as f:
        return json.load(f)


# === Structure Tests ===

class TestReportStructure:
    def test_top_level_keys(self, report):
        assert "workloads" in report
        assert "stack_analysis" in report
        assert "validation" in report

    def test_all_workloads_present(self, report):
        for wl in ["matrix_multiply", "sort_benchmark", "web_server"]:
            assert wl in report["workloads"], f"Missing workload: {wl}"

    def test_workload_configs(self, report):
        for wl in ["matrix_multiply", "sort_benchmark", "web_server"]:
            w = report["workloads"][wl]
            assert "baseline" in w, f"{wl} missing baseline"
            assert "modified" in w, f"{wl} missing modified"
            assert "regression" in w, f"{wl} missing regression"

    def test_baseline_metric_keys(self, report):
        keys = {"ipc", "cache_miss_rate", "branch_miss_rate",
                "frontend_stall_ratio", "backend_stall_ratio", "classification"}
        for wl in ["matrix_multiply", "sort_benchmark", "web_server"]:
            for cfg in ["baseline", "modified"]:
                actual = set(report["workloads"][wl][cfg].keys())
                assert keys.issubset(actual), f"{wl}/{cfg} missing keys: {keys - actual}"


# === Matrix Multiply Tests ===

class TestMatrixMultiply:
    def test_baseline_ipc(self, report):
        m = report["workloads"]["matrix_multiply"]["baseline"]
        assert abs(m["ipc"] - 2.0) < 0.01

    def test_baseline_cache_miss_rate(self, report):
        m = report["workloads"]["matrix_multiply"]["baseline"]
        assert abs(m["cache_miss_rate"] - 0.023) < 0.005

    def test_baseline_branch_miss_rate(self, report):
        m = report["workloads"]["matrix_multiply"]["baseline"]
        assert abs(m["branch_miss_rate"] - 0.018) < 0.005

    def test_baseline_frontend_stall(self, report):
        m = report["workloads"]["matrix_multiply"]["baseline"]
        assert abs(m["frontend_stall_ratio"] - 0.08) < 0.01

    def test_baseline_backend_stall(self, report):
        m = report["workloads"]["matrix_multiply"]["baseline"]
        assert abs(m["backend_stall_ratio"] - 0.12) < 0.01

    def test_baseline_classification(self, report):
        m = report["workloads"]["matrix_multiply"]["baseline"]
        assert m["classification"] == "compute-bound"

    def test_modified_ipc(self, report):
        m = report["workloads"]["matrix_multiply"]["modified"]
        assert abs(m["ipc"] - 0.78) < 0.01

    def test_modified_cache_miss_rate(self, report):
        m = report["workloads"]["matrix_multiply"]["modified"]
        assert abs(m["cache_miss_rate"] - 0.312) < 0.005

    def test_modified_backend_stall(self, report):
        m = report["workloads"]["matrix_multiply"]["modified"]
        assert abs(m["backend_stall_ratio"] - 0.58) < 0.01

    def test_modified_classification(self, report):
        m = report["workloads"]["matrix_multiply"]["modified"]
        assert m["classification"] == "memory-bound"

    def test_regression_detected(self, report):
        r = report["workloads"]["matrix_multiply"]["regression"]
        assert r["detected"] is True

    def test_regression_ipc_delta(self, report):
        r = report["workloads"]["matrix_multiply"]["regression"]
        assert abs(r["ipc_delta"] - (-1.22)) < 0.01

    def test_regression_primary_cause(self, report):
        r = report["workloads"]["matrix_multiply"]["regression"]
        assert r["primary_cause"] == "cache_miss_increase"

    def test_regression_severity(self, report):
        r = report["workloads"]["matrix_multiply"]["regression"]
        assert r["severity"] == "critical"


# === Sort Benchmark Tests ===

class TestSortBenchmark:
    def test_baseline_ipc(self, report):
        m = report["workloads"]["sort_benchmark"]["baseline"]
        assert abs(m["ipc"] - 1.2) < 0.01

    def test_baseline_classification(self, report):
        m = report["workloads"]["sort_benchmark"]["baseline"]
        assert m["classification"] == "mixed"

    def test_modified_ipc(self, report):
        m = report["workloads"]["sort_benchmark"]["modified"]
        assert abs(m["ipc"] - 0.9) < 0.01

    def test_modified_branch_miss_rate(self, report):
        m = report["workloads"]["sort_benchmark"]["modified"]
        assert abs(m["branch_miss_rate"] - 0.08) < 0.005

    def test_modified_frontend_stall_null(self, report):
        """stalled-cycles-frontend is <not supported> in sort_benchmark modified."""
        m = report["workloads"]["sort_benchmark"]["modified"]
        assert m["frontend_stall_ratio"] is None

    def test_modified_classification(self, report):
        m = report["workloads"]["sort_benchmark"]["modified"]
        assert m["classification"] == "branch-heavy"

    def test_regression_detected(self, report):
        r = report["workloads"]["sort_benchmark"]["regression"]
        assert r["detected"] is True

    def test_regression_ipc_delta(self, report):
        r = report["workloads"]["sort_benchmark"]["regression"]
        assert abs(r["ipc_delta"] - (-0.3)) < 0.01

    def test_regression_primary_cause(self, report):
        r = report["workloads"]["sort_benchmark"]["regression"]
        assert r["primary_cause"] == "branch_prediction_degradation"

    def test_regression_severity(self, report):
        r = report["workloads"]["sort_benchmark"]["regression"]
        assert r["severity"] == "moderate"


# === Web Server Tests ===

class TestWebServer:
    def test_baseline_ipc(self, report):
        m = report["workloads"]["web_server"]["baseline"]
        assert abs(m["ipc"] - 1.1) < 0.01

    def test_baseline_classification(self, report):
        m = report["workloads"]["web_server"]["baseline"]
        assert m["classification"] == "mixed"

    def test_modified_ipc(self, report):
        m = report["workloads"]["web_server"]["modified"]
        assert abs(m["ipc"] - 1.0) < 0.01

    def test_modified_classification(self, report):
        m = report["workloads"]["web_server"]["modified"]
        assert m["classification"] == "mixed"

    def test_regression_not_detected(self, report):
        """IPC decrease is ~9.09% which is below the 10% threshold."""
        r = report["workloads"]["web_server"]["regression"]
        assert r["detected"] is False

    def test_regression_ipc_delta(self, report):
        r = report["workloads"]["web_server"]["regression"]
        assert abs(r["ipc_delta"] - (-0.1)) < 0.02

    def test_regression_cause_none(self, report):
        r = report["workloads"]["web_server"]["regression"]
        assert r["primary_cause"] == "none"

    def test_regression_severity_none(self, report):
        r = report["workloads"]["web_server"]["regression"]
        assert r["severity"] == "none"


# === Validation Tests ===

class TestValidation:
    def test_matrix_multiply_not_noisy(self, report):
        v = report["validation"]["matrix_multiply"]
        assert v["noisy_system"] is False

    def test_matrix_multiply_no_migration(self, report):
        v = report["validation"]["matrix_multiply"]
        assert v["migration_issues"] is False

    def test_sort_benchmark_not_noisy(self, report):
        v = report["validation"]["sort_benchmark"]
        assert v["noisy_system"] is False

    def test_sort_benchmark_no_migration(self, report):
        v = report["validation"]["sort_benchmark"]
        assert v["migration_issues"] is False

    def test_web_server_noisy(self, report):
        v = report["validation"]["web_server"]
        assert v["noisy_system"] is True

    def test_web_server_migration_issues(self, report):
        v = report["validation"]["web_server"]
        assert v["migration_issues"] is True


# === Stack Analysis Tests ===

class TestStackAnalysis:
    def test_stack_analysis_present(self, report):
        assert "matrix_multiply" in report["stack_analysis"]
        sa = report["stack_analysis"]["matrix_multiply"]
        assert "top_regressions" in sa
        assert "top_consumers_modified" in sa

    def test_top_regressions_count(self, report):
        regs = report["stack_analysis"]["matrix_multiply"]["top_regressions"]
        assert len(regs) >= 3

    def test_top_regression_1_function(self, report):
        regs = report["stack_analysis"]["matrix_multiply"]["top_regressions"]
        assert regs[0]["function"] == "__cache_miss_stall"

    def test_top_regression_2_function(self, report):
        regs = report["stack_analysis"]["matrix_multiply"]["top_regressions"]
        assert regs[1]["function"] == "element_access"

    def test_top_regression_3_function(self, report):
        regs = report["stack_analysis"]["matrix_multiply"]["top_regressions"]
        assert regs[2]["function"] == "stride_compute"

    def test_top_regression_1_values(self, report):
        r0 = report["stack_analysis"]["matrix_multiply"]["top_regressions"][0]
        assert abs(r0["baseline_pct"] - 0.0) < 0.01
        assert abs(r0["modified_pct"] - 23.73) < 1.0
        assert abs(r0["delta"] - 23.73) < 1.0

    def test_top_regression_2_values(self, report):
        r1 = report["stack_analysis"]["matrix_multiply"]["top_regressions"][1]
        assert abs(r1["baseline_pct"] - 0.0) < 0.01
        assert abs(r1["modified_pct"] - 18.64) < 1.0

    def test_top_consumers_count(self, report):
        cons = report["stack_analysis"]["matrix_multiply"]["top_consumers_modified"]
        assert len(cons) >= 3

    def test_top_consumer_1(self, report):
        cons = report["stack_analysis"]["matrix_multiply"]["top_consumers_modified"]
        assert cons[0]["function"] == "__cache_miss_stall"
        assert abs(cons[0]["exclusive_pct"] - 23.73) < 1.0

    def test_top_consumer_2(self, report):
        cons = report["stack_analysis"]["matrix_multiply"]["top_consumers_modified"]
        assert cons[1]["function"] == "element_access"
        assert abs(cons[1]["exclusive_pct"] - 18.64) < 1.0

    def test_top_consumer_3(self, report):
        cons = report["stack_analysis"]["matrix_multiply"]["top_consumers_modified"]
        assert cons[2]["function"] == "accumulate"
        assert abs(cons[2]["exclusive_pct"] - 16.10) < 1.0

    def test_element_access_inclusive_gt_exclusive(self, report):
        """element_access has children (__cache_miss_stall), so inclusive > exclusive."""
        cons = report["stack_analysis"]["matrix_multiply"]["top_consumers_modified"]
        elem = [c for c in cons if c["function"] == "element_access"]
        assert len(elem) == 1
        assert elem[0]["inclusive_pct"] > elem[0]["exclusive_pct"]
        assert abs(elem[0]["inclusive_pct"] - 42.37) < 1.0

    def test_cache_miss_stall_inclusive_eq_exclusive(self, report):
        """__cache_miss_stall is always a leaf, so inclusive == exclusive."""
        cons = report["stack_analysis"]["matrix_multiply"]["top_consumers_modified"]
        cms = [c for c in cons if c["function"] == "__cache_miss_stall"]
        assert len(cms) == 1
        assert abs(cms[0]["inclusive_pct"] - cms[0]["exclusive_pct"]) < 0.01


# === Differential Flame Graph Tests ===

class TestDiffFlamegraph:
    def test_svg_file_exists(self):
        assert os.path.exists("/app/diff_flamegraph.svg"), \
            "Differential flame graph SVG not generated at /app/diff_flamegraph.svg"

    def test_svg_valid_markup(self):
        with open("/app/diff_flamegraph.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), "File does not contain SVG markup"
        assert "</svg>" in content.lower(), "SVG file is not properly closed"

    def test_svg_contains_key_functions(self):
        with open("/app/diff_flamegraph.svg") as f:
            content = f.read()
        assert "cache_miss_stall" in content, \
            "__cache_miss_stall should appear in differential flame graph"
        assert "element_access" in content, \
            "element_access should appear in differential flame graph"

    def test_svg_nontrivial_size(self):
        size = os.path.getsize("/app/diff_flamegraph.svg")
        assert size > 1000, f"SVG file suspiciously small ({size} bytes)"
