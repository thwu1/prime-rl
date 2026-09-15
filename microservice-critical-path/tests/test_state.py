"""Tests for critical path analyzer.

"""

import json
import subprocess
import pytest

ANALYZER = "/app/crisp_analyzer.py"
DB_PATH = "/app/traces.db"
OUTPUT = "/app/results.json"


@pytest.fixture(scope="session")
def results():
    """Run the analyzer and load results."""
    proc = subprocess.run(
        ["python3", ANALYZER,
         "--db", DB_PATH,
         "--service", "gateway",
         "--operation", "handleRequest",
         "--output", OUTPUT],
        capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, (
        f"Analyzer failed with code {proc.returncode}.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    with open(OUTPUT) as f:
        return json.load(f)


def get_trace(results, trace_id):
    for t in results["per_trace"]:
        if t["trace_id"] == trace_id:
            return t
    return None


def get_cp_entry(trace, service, operation):
    for entry in trace["critical_path"]:
        if entry["service"] == service and entry["operation"] == operation:
            return entry
    return None


# ===== Basic output structure =====

class TestOutputStructure:
    def test_num_traces(self, results):
        assert results["num_traces"] == 10

    def test_service_field(self, results):
        assert results["service"] == "gateway"

    def test_operation_field(self, results):
        assert results["operation"] == "handleRequest"

    def test_per_trace_sorted_by_trace_id(self, results):
        trace_ids = [t["trace_id"] for t in results["per_trace"]]
        assert trace_ids == sorted(trace_ids)

    def test_all_traces_present(self, results):
        trace_ids = {t["trace_id"] for t in results["per_trace"]}
        expected = {"t001", "t002", "t003", "t004", "t005",
                    "t006", "t007", "t008", "t009", "t010"}
        assert trace_ids == expected

    def test_percentiles_keys(self, results):
        assert "p50" in results["percentiles"]
        assert "p95" in results["percentiles"]
        assert "p99" in results["percentiles"]


# ===== Trace 1: 100ms =====

class TestTrace001:
    def test_end_to_end(self, results):
        t = get_trace(results, "t001")
        assert t is not None
        assert t["end_to_end_us"] == 100000

    def test_gateway_exclusive(self, results):
        t = get_trace(results, "t001")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e is not None
        assert e["exclusive_us"] == 70000

    def test_gateway_inclusive(self, results):
        t = get_trace(results, "t001")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["inclusive_us"] == 100000

    def test_auth_exclusive(self, results):
        t = get_trace(results, "t001")
        e = get_cp_entry(t, "auth", "validate")
        assert e is not None
        assert e["exclusive_us"] == 10000

    def test_auth_inclusive(self, results):
        t = get_trace(results, "t001")
        e = get_cp_entry(t, "auth", "validate")
        assert e["inclusive_us"] == 30000

    def test_userdb_exclusive(self, results):
        t = get_trace(results, "t001")
        e = get_cp_entry(t, "userdb", "lookup")
        assert e is not None
        assert e["exclusive_us"] == 20000

    def test_userdb_inclusive(self, results):
        t = get_trace(results, "t001")
        e = get_cp_entry(t, "userdb", "lookup")
        assert e["inclusive_us"] == 20000


# ===== Trace 2: 200ms =====

class TestTrace002:
    def test_end_to_end(self, results):
        t = get_trace(results, "t002")
        assert t["end_to_end_us"] == 200000

    def test_shorter_child_not_on_cp(self, results):
        t = get_trace(results, "t002")
        e = get_cp_entry(t, "serviceA", "fetch")
        assert e is None

    def test_longer_child_exclusive(self, results):
        t = get_trace(results, "t002")
        e = get_cp_entry(t, "serviceB", "fetch")
        assert e is not None
        assert e["exclusive_us"] == 150000

    def test_longer_child_inclusive(self, results):
        t = get_trace(results, "t002")
        e = get_cp_entry(t, "serviceB", "fetch")
        assert e["inclusive_us"] == 150000

    def test_gateway_exclusive(self, results):
        t = get_trace(results, "t002")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 50000


# ===== Trace 3: 100ms =====

class TestTrace003:
    def test_end_to_end(self, results):
        t = get_trace(results, "t003")
        assert t["end_to_end_us"] == 100000

    def test_db_exclusive(self, results):
        t = get_trace(results, "t003")
        e = get_cp_entry(t, "db", "query")
        assert e is not None
        assert e["exclusive_us"] == 80000

    def test_db_inclusive(self, results):
        t = get_trace(results, "t003")
        e = get_cp_entry(t, "db", "query")
        assert e["inclusive_us"] == 80000

    def test_backend_exclusive(self, results):
        t = get_trace(results, "t003")
        e = get_cp_entry(t, "backend", "process")
        assert e is not None
        assert e["exclusive_us"] == 10000

    def test_backend_inclusive(self, results):
        t = get_trace(results, "t003")
        e = get_cp_entry(t, "backend", "process")
        assert e["inclusive_us"] == 90000

    def test_gateway_exclusive(self, results):
        t = get_trace(results, "t003")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 10000


# ===== Trace 4: 150ms =====

class TestTrace004:
    def test_end_to_end(self, results):
        t = get_trace(results, "t004")
        assert t["end_to_end_us"] == 150000

    def test_analytics_not_on_cp(self, results):
        t = get_trace(results, "t004")
        e = get_cp_entry(t, "analytics", "log")
        assert e is None

    def test_backend_exclusive(self, results):
        t = get_trace(results, "t004")
        e = get_cp_entry(t, "backend", "process")
        assert e is not None
        assert e["exclusive_us"] == 70000

    def test_auth_exclusive(self, results):
        t = get_trace(results, "t004")
        e = get_cp_entry(t, "auth", "validate")
        assert e is not None
        assert e["exclusive_us"] == 40000

    def test_gateway_exclusive(self, results):
        t = get_trace(results, "t004")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 40000


# ===== Trace 5: 300ms =====

class TestTrace005:
    def test_end_to_end(self, results):
        t = get_trace(results, "t005")
        assert t["end_to_end_us"] == 300000

    def test_serviceE_exclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceE", "compute")
        assert e is not None
        assert e["exclusive_us"] == 90000

    def test_serviceC_exclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceC", "query")
        assert e is not None
        assert e["exclusive_us"] == 80000

    def test_serviceA_exclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceA", "process")
        assert e is not None
        assert e["exclusive_us"] == 60000

    def test_serviceD_exclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceD", "call")
        assert e is not None
        assert e["exclusive_us"] == 30000

    def test_serviceB_exclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceB", "call")
        assert e is not None
        assert e["exclusive_us"] == 20000

    def test_gateway_exclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 20000

    def test_serviceA_inclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceA", "process")
        assert e["inclusive_us"] == 280000

    def test_serviceD_inclusive(self, results):
        t = get_trace(results, "t005")
        e = get_cp_entry(t, "serviceD", "call")
        assert e["inclusive_us"] == 120000

    def test_six_entries_on_cp(self, results):
        t = get_trace(results, "t005")
        assert len(t["critical_path"]) == 6


# ===== Traces 6-10 =====

class TestTrace006:
    def test_end_to_end(self, results):
        t = get_trace(results, "t006")
        assert t["end_to_end_us"] == 120000

    def test_gateway(self, results):
        t = get_trace(results, "t006")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 30000

    def test_backend(self, results):
        t = get_trace(results, "t006")
        e = get_cp_entry(t, "backend", "process")
        assert e["exclusive_us"] == 90000


class TestTrace007:
    def test_end_to_end(self, results):
        t = get_trace(results, "t007")
        assert t["end_to_end_us"] == 140000

    def test_gateway(self, results):
        t = get_trace(results, "t007")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 40000

    def test_auth(self, results):
        t = get_trace(results, "t007")
        e = get_cp_entry(t, "auth", "validate")
        assert e["exclusive_us"] == 30000

    def test_backend(self, results):
        t = get_trace(results, "t007")
        e = get_cp_entry(t, "backend", "process")
        assert e["exclusive_us"] == 70000


class TestTrace008:
    def test_end_to_end(self, results):
        t = get_trace(results, "t008")
        assert t["end_to_end_us"] == 160000

    def test_gateway(self, results):
        t = get_trace(results, "t008")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 50000

    def test_backend(self, results):
        t = get_trace(results, "t008")
        e = get_cp_entry(t, "backend", "process")
        assert e["exclusive_us"] == 110000


class TestTrace009:
    def test_end_to_end(self, results):
        t = get_trace(results, "t009")
        assert t["end_to_end_us"] == 180000

    def test_gateway(self, results):
        t = get_trace(results, "t009")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 30000

    def test_auth(self, results):
        t = get_trace(results, "t009")
        e = get_cp_entry(t, "auth", "validate")
        assert e["exclusive_us"] == 50000

    def test_backend(self, results):
        t = get_trace(results, "t009")
        e = get_cp_entry(t, "backend", "process")
        assert e["exclusive_us"] == 100000


class TestTrace010:
    def test_end_to_end(self, results):
        t = get_trace(results, "t010")
        assert t["end_to_end_us"] == 250000

    def test_gateway(self, results):
        t = get_trace(results, "t010")
        e = get_cp_entry(t, "gateway", "handleRequest")
        assert e["exclusive_us"] == 80000

    def test_backend(self, results):
        t = get_trace(results, "t010")
        e = get_cp_entry(t, "backend", "process")
        assert e["exclusive_us"] == 170000


# ===== Percentile tests =====

class TestPercentiles:
    def test_p50_latency(self, results):
        assert results["percentiles"]["p50"]["latency_us"] == 150000

    def test_p50_trace(self, results):
        assert results["percentiles"]["p50"]["trace_id"] == "t004"

    def test_p95_latency(self, results):
        assert results["percentiles"]["p95"]["latency_us"] == 300000

    def test_p95_trace(self, results):
        assert results["percentiles"]["p95"]["trace_id"] == "t005"

    def test_p99_latency(self, results):
        assert results["percentiles"]["p99"]["latency_us"] == 300000

    def test_p99_trace(self, results):
        assert results["percentiles"]["p99"]["trace_id"] == "t005"


# ===== Consistency checks =====

class TestConsistency:

    @pytest.mark.parametrize("trace_id,expected_e2e", [
        ("t001", 100000), ("t002", 200000), ("t003", 100000),
        ("t004", 150000), ("t005", 300000), ("t006", 120000),
        ("t007", 140000), ("t008", 160000), ("t009", 180000),
        ("t010", 250000),
    ])
    def test_exclusive_sum_equals_end_to_end(self, results, trace_id, expected_e2e):
        t = get_trace(results, trace_id)
        assert t is not None, f"Trace {trace_id} not found"
        assert t["end_to_end_us"] == expected_e2e
        total = sum(e["exclusive_us"] for e in t["critical_path"])
        assert total == expected_e2e, (
            f"Exclusive sum {total} != e2e {expected_e2e} for {trace_id}"
        )

    def test_inclusive_gte_exclusive(self, results):
        for t in results["per_trace"]:
            for e in t["critical_path"]:
                assert e["inclusive_us"] >= e["exclusive_us"], (
                    f"inclusive < exclusive for {e['service']}.{e['operation']} "
                    f"in {t['trace_id']}"
                )

    def test_cp_sort_order(self, results):
        for t in results["per_trace"]:
            cp = t["critical_path"]
            for i in range(len(cp) - 1):
                a, b = cp[i], cp[i + 1]
                if a["exclusive_us"] == b["exclusive_us"]:
                    key_a = (a["service"], a["operation"])
                    key_b = (b["service"], b["operation"])
                    assert key_a <= key_b, (
                        f"Tie-break sort wrong in {t['trace_id']}: "
                        f"{key_a} should come before {key_b}"
                    )
                else:
                    assert a["exclusive_us"] > b["exclusive_us"], (
                        f"Sort order wrong in {t['trace_id']}: "
                        f"{a['exclusive_us']} should be > {b['exclusive_us']}"
                    )

    def test_all_exclusive_positive(self, results):
        for t in results["per_trace"]:
            for e in t["critical_path"]:
                assert e["exclusive_us"] > 0, (
                    f"Zero/negative exclusive for {e['service']}.{e['operation']} "
                    f"in {t['trace_id']}"
                )
