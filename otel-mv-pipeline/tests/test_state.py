#!/usr/bin/env python3
"""Tests for the ClickHouse observability pipeline task."""

import pytest
import subprocess
import csv
import os
from collections import defaultdict


def run_ch_query(query):
    """Run a ClickHouse query and return (stdout, returncode)."""
    result = subprocess.run(
        ["clickhouse-client", "--query", query],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip(), result.returncode


def load_csv(path):
    """Load a CSV file and return rows as list of dicts."""
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_raw_telemetry():
    """Load raw telemetry data for independent verification."""
    return load_csv("/app/data/telemetry.csv")


def compute_p99(values):
    """Compute 99th percentile using linear interpolation."""
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 0:
        return 0
    if n == 1:
        return sorted_vals[0]
    idx = 0.99 * (n - 1)
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    weight = idx - lower
    return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight


class TestClickHouseRunning:
    def test_server_is_running(self):
        output, rc = run_ch_query("SELECT 1")
        assert rc == 0, "ClickHouse server is not running"
        assert output == "1"


class TestDatabaseAndTable:
    def test_database_exists(self):
        output, rc = run_ch_query(
            "SELECT name FROM system.databases WHERE name = 'observability'"
        )
        assert rc == 0
        assert "observability" in output, "Database 'observability' does not exist"

    def test_table_exists(self):
        output, rc = run_ch_query(
            "SELECT name FROM system.tables WHERE database = 'observability' AND name = 'spans'"
        )
        assert rc == 0
        assert "spans" in output, "Table 'observability.spans' does not exist"

    def test_table_engine_is_mergetree(self):
        output, rc = run_ch_query(
            "SELECT engine FROM system.tables WHERE database = 'observability' AND name = 'spans'"
        )
        assert rc == 0
        assert "MergeTree" in output, (
            f"Table engine should be MergeTree family, got: {output}"
        )

    def test_sorting_key_includes_service_name(self):
        output, rc = run_ch_query(
            "SELECT sorting_key FROM system.tables WHERE database = 'observability' AND name = 'spans'"
        )
        assert rc == 0
        assert "service_name" in output, (
            f"Sorting key should include service_name, got: {output}"
        )

    def test_row_count_matches(self):
        with open("/app/data/row_count.txt") as f:
            expected_count = int(f.read().strip())
        output, rc = run_ch_query("SELECT count() FROM observability.spans")
        assert rc == 0
        actual_count = int(output)
        assert actual_count == expected_count, (
            f"Expected {expected_count} rows, got {actual_count}"
        )

    def test_low_cardinality_on_service_name(self):
        output, rc = run_ch_query(
            "SELECT type FROM system.columns "
            "WHERE database = 'observability' AND table = 'spans' "
            "AND name = 'service_name'"
        )
        assert rc == 0
        assert "LowCardinality" in output, (
            f"service_name should use LowCardinality type, got: {output}"
        )


class TestMaterializedViews:
    def test_at_least_two_materialized_views(self):
        output, rc = run_ch_query(
            "SELECT count() FROM system.tables "
            "WHERE database = 'observability' AND engine = 'MaterializedView'"
        )
        assert rc == 0
        mv_count = int(output)
        assert mv_count >= 2, (
            f"Expected at least 2 materialized views, found {mv_count}"
        )

    def test_materialized_views_have_data(self):
        # Get names of MV target tables
        output, rc = run_ch_query(
            "SELECT name FROM system.tables "
            "WHERE database = 'observability' AND engine = 'MaterializedView'"
        )
        assert rc == 0
        mv_names = [n.strip() for n in output.split("\n") if n.strip()]

        for mv_name in mv_names:
            count_out, count_rc = run_ch_query(
                f"SELECT count() FROM observability.`{mv_name}`"
            )
            if count_rc != 0:
                # MV might use a separate target table; try the .inner table
                count_out, count_rc = run_ch_query(
                    f"SELECT count() FROM observability.`.inner.{mv_name}`"
                )
            if count_rc == 0:
                count = int(count_out)
                assert count > 0, (
                    f"Materialized view '{mv_name}' has no data (expected POPULATE or backfill)"
                )


class TestTopErrorServices:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.raw_data = load_raw_telemetry()

    def test_file_exists(self):
        assert os.path.exists("/app/results/top_error_services.csv"), (
            "top_error_services.csv not found"
        )

    def test_correctness(self):
        # Compute expected from raw data
        service_stats = defaultdict(lambda: {"total": 0, "errors": 0})
        for row in self.raw_data:
            svc = row["service_name"]
            service_stats[svc]["total"] += 1
            if int(row["status_code"]) >= 400:
                service_stats[svc]["errors"] += 1

        error_rates = []
        for svc, stats in service_stats.items():
            rate = stats["errors"] / stats["total"] if stats["total"] > 0 else 0
            error_rates.append((svc, stats["total"], stats["errors"], rate))
        error_rates.sort(key=lambda x: -x[3])
        top3_expected = error_rates[:3]

        actual = load_csv("/app/results/top_error_services.csv")
        assert len(actual) == 3, (
            f"Expected 3 rows in top_error_services.csv, got {len(actual)}"
        )

        for i, (exp_svc, exp_total, exp_errors, exp_rate) in enumerate(top3_expected):
            assert actual[i]["service_name"] == exp_svc, (
                f"Row {i}: expected service '{exp_svc}', "
                f"got '{actual[i]['service_name']}'"
            )
            assert int(actual[i]["total_requests"]) == exp_total, (
                f"Row {i}: expected total {exp_total}, "
                f"got {actual[i]['total_requests']}"
            )
            assert int(actual[i]["error_count"]) == exp_errors, (
                f"Row {i}: expected errors {exp_errors}, "
                f"got {actual[i]['error_count']}"
            )
            actual_rate = float(actual[i]["error_rate"])
            assert abs(actual_rate - exp_rate) < 0.002, (
                f"Row {i}: expected rate ~{exp_rate:.4f}, got {actual_rate}"
            )


class TestP99ByService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.raw_data = load_raw_telemetry()

    def test_file_exists(self):
        assert os.path.exists("/app/results/p99_by_service.csv"), (
            "p99_by_service.csv not found"
        )

    def test_correctness(self):
        # Compute expected P99 per service
        service_durations = defaultdict(list)
        for row in self.raw_data:
            service_durations[row["service_name"]].append(int(row["duration_us"]))

        expected_p99 = {}
        for svc, durations in service_durations.items():
            expected_p99[svc] = compute_p99(durations)

        actual = load_csv("/app/results/p99_by_service.csv")
        actual_p99 = {
            row["service_name"]: int(row["p99_duration_us"]) for row in actual
        }

        assert set(actual_p99.keys()) == set(expected_p99.keys()), (
            f"Service names don't match: "
            f"expected {sorted(expected_p99.keys())}, "
            f"got {sorted(actual_p99.keys())}"
        )

        for svc in expected_p99:
            expected = expected_p99[svc]
            actual_val = actual_p99[svc]
            tolerance = max(expected * 0.05, 500)
            assert abs(actual_val - expected) <= tolerance, (
                f"P99 for {svc}: expected ~{expected:.0f}, "
                f"got {actual_val} (tolerance: {tolerance:.0f})"
            )

    def test_ordering(self):
        actual = load_csv("/app/results/p99_by_service.csv")
        names = [row["service_name"] for row in actual]
        assert names == sorted(names), (
            "p99_by_service.csv should be ordered alphabetically by service_name"
        )


class TestDeepTraces:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.raw_data = load_raw_telemetry()

    def test_file_exists(self):
        assert os.path.exists("/app/results/deep_traces.csv"), (
            "deep_traces.csv not found"
        )

    def test_correctness(self):
        # Compute expected deep traces
        trace_spans = defaultdict(int)
        for row in self.raw_data:
            trace_spans[row["trace_id"]] += 1

        expected_deep = {
            tid: count for tid, count in trace_spans.items() if count > 5
        }

        actual = load_csv("/app/results/deep_traces.csv")
        actual_deep = {
            row["trace_id"]: int(row["span_count"]) for row in actual
        }

        assert len(actual_deep) == len(expected_deep), (
            f"Expected {len(expected_deep)} deep traces, got {len(actual_deep)}"
        )

        for tid in expected_deep:
            assert tid in actual_deep, f"Missing deep trace: {tid}"
            assert actual_deep[tid] == expected_deep[tid], (
                f"Trace {tid}: expected {expected_deep[tid]} spans, "
                f"got {actual_deep[tid]}"
            )

    def test_ordering(self):
        actual = load_csv("/app/results/deep_traces.csv")
        for i in range(len(actual) - 1):
            cur_count = int(actual[i]["span_count"])
            next_count = int(actual[i + 1]["span_count"])
            assert cur_count >= next_count, (
                "deep_traces.csv should be sorted by span_count DESC"
            )
            if cur_count == next_count:
                assert actual[i]["trace_id"] <= actual[i + 1]["trace_id"], (
                    "deep_traces.csv should break ties by trace_id ASC"
                )


class TestErrorCorrelation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.raw_data = load_raw_telemetry()

    def test_file_exists(self):
        assert os.path.exists("/app/results/error_correlation.csv"), (
            "error_correlation.csv not found"
        )

    def test_correctness(self):
        # Compute: for each service, the operation with the highest error count
        service_op_errors = defaultdict(lambda: defaultdict(int))
        services_seen = set()
        for row in self.raw_data:
            services_seen.add(row["service_name"])
            if int(row["status_code"]) >= 400:
                service_op_errors[row["service_name"]][row["operation_name"]] += 1

        expected = {}
        for svc in services_seen:
            if svc in service_op_errors and service_op_errors[svc]:
                max_count = max(service_op_errors[svc].values())
                max_ops = [
                    op for op, cnt in service_op_errors[svc].items()
                    if cnt == max_count
                ]
                expected[svc] = (max_ops, max_count)

        actual = load_csv("/app/results/error_correlation.csv")
        actual_corr = {
            row["service_name"]: (row["operation_name"], int(row["error_count"]))
            for row in actual
        }

        assert set(actual_corr.keys()) == set(expected.keys()), (
            f"Services don't match: "
            f"expected {sorted(expected.keys())}, "
            f"got {sorted(actual_corr.keys())}"
        )

        for svc in expected:
            valid_ops, exp_count = expected[svc]
            act_op, act_count = actual_corr[svc]
            assert act_count == exp_count, (
                f"Service {svc}: expected error count {exp_count}, "
                f"got {act_count}"
            )
            assert act_op in valid_ops, (
                f"Service {svc}: expected one of {valid_ops}, got '{act_op}'"
            )

    def test_ordering(self):
        actual = load_csv("/app/results/error_correlation.csv")
        names = [row["service_name"] for row in actual]
        assert names == sorted(names), (
            "error_correlation.csv should be ordered alphabetically by service_name"
        )
