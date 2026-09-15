"""Tests for the tail-based trace sampling pipeline output."""

import json
import subprocess
import pytest
from collections import defaultdict


def load_jsonl(path):
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def is_root_span(span):
    """Root spans have no parent: empty string, missing field, or zero-padded hex."""
    parent = span.get("parent_span_id")
    if parent is None:
        return True
    if parent == "":
        return True
    if parent == "0000000000000000":
        return True
    return False


def group_by_trace(spans):
    traces = defaultdict(list)
    for span in spans:
        traces[span["trace_id"]].append(span)
    return dict(traces)


def trace_has_error(spans):
    """Check if any span in the trace indicates an error condition."""
    for span in spans:
        if span.get("error", False) is True:
            return True
        if isinstance(span.get("http_status_code"), (int, float)):
            if span["http_status_code"] >= 500:
                return True
    return False


def trace_root_exceeds_threshold(spans, threshold_ms):
    """Check if any root span's duration exceeds the given threshold."""
    for span in spans:
        if is_root_span(span):
            duration = span.get("duration_ms", 0)
            if isinstance(duration, (int, float)) and duration > threshold_ms:
                return True
    return False


class TestSamplingPipelineOutput:
    """Verify the tail-based sampling pipeline produces correct output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.raw_spans = load_jsonl("/app/data/spans.jsonl")
        self.raw_traces = group_by_trace(self.raw_spans)

        self.sampled_spans = load_jsonl("/app/output/sampled_spans.jsonl")
        self.sampled_traces = group_by_trace(self.sampled_spans)

        with open("/app/output/sampling_report.json") as f:
            self.sampling_report = json.load(f)

        with open("/app/output/slo_report.json") as f:
            self.slo_report = json.load(f)

    def test_output_exists_and_nonempty(self):
        """Sampled output must exist and contain spans."""
        assert len(self.sampled_spans) > 0, "sampled_spans.jsonl is empty"
        for span in self.sampled_spans:
            assert "trace_id" in span
            assert "span_id" in span

    def test_all_error_traces_kept(self):
        """Every trace with an error span must be in the output (100% recall)."""
        error_trace_ids = {
            tid
            for tid, spans in self.raw_traces.items()
            if trace_has_error(spans)
        }
        sampled_trace_ids = set(self.sampled_traces.keys())

        missing = error_trace_ids - sampled_trace_ids
        assert len(missing) == 0, (
            f"Missing {len(missing)} error traces from output: "
            f"{list(missing)[:5]}"
        )

    def test_all_slo_violation_traces_kept(self):
        """Every trace where root span exceeds 500ms must be in the output."""
        slo_violation_ids = {
            tid
            for tid, spans in self.raw_traces.items()
            if trace_root_exceeds_threshold(spans, 500.0)
        }
        sampled_trace_ids = set(self.sampled_traces.keys())

        missing = slo_violation_ids - sampled_trace_ids
        assert len(missing) == 0, (
            f"Missing {len(missing)} SLO-violation traces from output"
        )

    def test_adaptive_latency_traces_kept(self):
        """Traces exceeding per-endpoint P95 latency must be kept."""
        route_durations = defaultdict(list)
        for span in self.raw_spans:
            if is_root_span(span) and "http_route" in span:
                route_durations[span["http_route"]].append(
                    span.get("duration_ms", 0)
                )

        p95_thresholds = {}
        for route, durations in route_durations.items():
            sorted_d = sorted(durations)
            idx = min(int(len(sorted_d) * 0.95), len(sorted_d) - 1)
            p95_thresholds[route] = sorted_d[idx]

        adaptive_violation_ids = set()
        for tid, spans in self.raw_traces.items():
            for span in spans:
                if is_root_span(span):
                    route = span.get("http_route")
                    duration = span.get("duration_ms", 0)
                    if route in p95_thresholds and duration > p95_thresholds[route]:
                        adaptive_violation_ids.add(tid)

        sampled_trace_ids = set(self.sampled_traces.keys())
        missing = adaptive_violation_ids - sampled_trace_ids
        assert len(missing) == 0, (
            f"Missing {len(missing)} adaptive-latency traces from output"
        )

    def test_anomalous_topology_traces_kept(self):
        """Traces with missing expected downstream services must be kept."""
        trace_route = {}
        for span in self.raw_spans:
            if is_root_span(span) and "http_route" in span:
                trace_route[span["trace_id"]] = span["http_route"]

        trace_services = defaultdict(set)
        for span in self.raw_spans:
            trace_services[span["trace_id"]].add(span.get("service_name"))

        route_traces = defaultdict(list)
        for tid, route in trace_route.items():
            route_traces[route].append(tid)

        route_expected = {}
        for route, tids in route_traces.items():
            svc_count = defaultdict(int)
            for tid in tids:
                for svc in trace_services[tid]:
                    svc_count[svc] += 1
            total = len(tids)
            route_expected[route] = {
                svc for svc, cnt in svc_count.items()
                if cnt / total >= 0.8
            }

        anomalous_ids = set()
        for tid, route in trace_route.items():
            expected = route_expected.get(route, set())
            actual = trace_services[tid]
            if expected - actual:
                anomalous_ids.add(tid)

        sampled_trace_ids = set(self.sampled_traces.keys())
        missing = anomalous_ids - sampled_trace_ids
        assert len(missing) == 0, (
            f"Missing {len(missing)} anomalous-topology traces from output"
        )

    def test_budget_respected(self):
        """Output must not exceed the 2000-trace budget."""
        assert len(self.sampled_traces) <= 2000, (
            f"Budget exceeded: {len(self.sampled_traces)} traces (max 2000)"
        )

    def test_sample_rate_annotations(self):
        """Every output span must have meta_sample_rate as an integer >= 1."""
        for span in self.sampled_spans:
            assert "meta_sample_rate" in span, (
                f"Missing meta_sample_rate on span {span['span_id']}"
            )
            rate = span["meta_sample_rate"]
            assert isinstance(rate, int) and rate >= 1, (
                f"Invalid meta_sample_rate={rate} on span {span['span_id']}"
            )

    def test_meta_rule_annotations(self):
        """Every output span must have a non-empty meta_rule string."""
        for span in self.sampled_spans:
            assert "meta_rule" in span, (
                f"Missing meta_rule on span {span['span_id']}"
            )
            assert isinstance(span["meta_rule"], str) and len(span["meta_rule"]) > 0

    def test_traces_are_complete(self):
        """All spans from a kept trace must be present in the output."""
        for tid, sampled in self.sampled_traces.items():
            raw = self.raw_traces.get(tid, [])
            raw_span_ids = {s["span_id"] for s in raw}
            sampled_span_ids = {s["span_id"] for s in sampled}
            assert sampled_span_ids == raw_span_ids, (
                f"Trace {tid}: expected {len(raw)} spans, got {len(sampled)} "
                f"(missing: {raw_span_ids - sampled_span_ids})"
            )

    def test_consistent_sample_rate_within_trace(self):
        """All spans in a trace must share the same meta_sample_rate."""
        for tid, spans in self.sampled_traces.items():
            rates = {s["meta_sample_rate"] for s in spans}
            assert len(rates) == 1, (
                f"Trace {tid}: inconsistent sample rates {rates}"
            )

    def test_error_traces_have_rate_1(self):
        """Error traces must be kept unconditionally (sample_rate=1)."""
        for tid, spans in self.sampled_traces.items():
            if trace_has_error(spans):
                for span in spans:
                    assert span["meta_sample_rate"] == 1, (
                        f"Error trace {tid} has rate "
                        f"{span['meta_sample_rate']}, expected 1"
                    )

    def test_dynamic_sampling_is_non_trivial(self):
        """Dynamic sampling should produce varying rates, not a trivial keep-all."""
        rates = set()
        for tid, spans in self.sampled_traces.items():
            rates.add(spans[0]["meta_sample_rate"])
        assert len(rates) >= 2, (
            f"Only found sample rates {rates}; "
            f"expected at least 2 distinct rates (1 for must-keep, >1 for dynamic)"
        )

    def test_weighted_availability_sli_accuracy(self):
        """Weighted availability SLI from sampled data must approximate
        the true SLI within 5% relative error."""
        raw_root = [
            s for s in self.raw_spans
            if is_root_span(s) and s.get("service_name") == "api-gateway"
        ]
        raw_good = sum(
            1 for s in raw_root if s.get("http_status_code", 200) < 500
        )
        raw_total = len(raw_root)
        assert raw_total > 0, "No api-gateway root spans in raw data"
        raw_sli = raw_good / raw_total

        sampled_root = [
            s for s in self.sampled_spans
            if is_root_span(s) and s.get("service_name") == "api-gateway"
        ]
        assert len(sampled_root) > 0, "No api-gateway root spans in sampled data"
        weighted_good = sum(
            s["meta_sample_rate"]
            for s in sampled_root
            if s.get("http_status_code", 200) < 500
        )
        weighted_total = sum(s["meta_sample_rate"] for s in sampled_root)
        sampled_sli = weighted_good / weighted_total

        relative_error = abs(sampled_sli - raw_sli) / raw_sli
        assert relative_error < 0.05, (
            f"SLI accuracy check failed: raw={raw_sli:.6f}, "
            f"sampled={sampled_sli:.6f}, relative_error={relative_error:.4f}"
        )

    def test_output_is_subset_of_raw(self):
        """Sampled traces must be a subset of raw traces."""
        raw_span_ids = {s["span_id"] for s in self.raw_spans}
        for span in self.sampled_spans:
            assert span["span_id"] in raw_span_ids, (
                f"Unknown span {span['span_id']} not in raw data"
            )

        for tid in self.sampled_traces:
            assert tid in self.raw_traces, (
                f"Unknown trace {tid} not in raw data"
            )

    def test_sampling_report_structure(self):
        """Sampling report must contain required keys and consistent counts."""
        required = ["total_traces", "kept_traces", "rules_breakdown",
                     "effective_rates"]
        for key in required:
            assert key in self.sampling_report, (
                f"Missing key '{key}' in sampling_report.json"
            )

        assert self.sampling_report["total_traces"] == len(self.raw_traces)
        assert self.sampling_report["kept_traces"] == len(self.sampled_traces)
        assert self.sampling_report["kept_traces"] <= 2000

    def test_slo_report_structure(self):
        """SLO report must contain valid SLI results."""
        assert "slos" in self.slo_report
        assert len(self.slo_report["slos"]) >= 1

        for slo in self.slo_report["slos"]:
            assert "name" in slo, "SLO entry missing 'name'"
            assert "raw_sli" in slo, "SLO entry missing 'raw_sli'"
            assert "sampled_sli" in slo, "SLO entry missing 'sampled_sli'"
            assert "target" in slo, "SLO entry missing 'target'"
            assert 0 <= slo["raw_sli"] <= 1, (
                f"raw_sli={slo['raw_sli']} out of [0,1]"
            )
            assert 0 <= slo["sampled_sli"] <= 1, (
                f"sampled_sli={slo['sampled_sli']} out of [0,1]"
            )

    def test_non_error_traces_sampled(self):
        """Verify that not all traces are kept — sampling actually occurred."""
        assert len(self.sampled_traces) < len(self.raw_traces), (
            f"No sampling occurred: {len(self.sampled_traces)} sampled == "
            f"{len(self.raw_traces)} raw"
        )

    def test_fairness_constraint(self):
        """Every (service_name, http_route) pair in raw data must appear
        in sampled data at least once."""
        raw_pairs = set()
        for span in self.raw_spans:
            svc = span.get("service_name")
            route = span.get("http_route")
            if svc and route:
                raw_pairs.add((svc, route))

        sampled_pairs = set()
        for span in self.sampled_spans:
            svc = span.get("service_name")
            route = span.get("http_route")
            if svc and route:
                sampled_pairs.add((svc, route))

        missing = raw_pairs - sampled_pairs
        assert len(missing) == 0, (
            f"Fairness violation: missing service-route pairs in output: {missing}"
        )

    def test_topology_structure(self):
        """topology.json must have correct structure with valid data."""
        with open("/app/output/topology.json") as f:
            topo = json.load(f)

        assert "services" in topo, "Missing 'services' in topology.json"
        assert "edges" in topo, "Missing 'edges' in topology.json"
        assert "expected_topologies" in topo, "Missing 'expected_topologies'"

        raw_services = {
            s.get("service_name") for s in self.raw_spans
            if s.get("service_name")
        }
        assert set(topo["services"]) == raw_services, (
            f"Services mismatch: expected {raw_services}, got {set(topo['services'])}"
        )

    def test_topology_edges_correct(self):
        """Service dependency edges must match actual parent-child relationships."""
        with open("/app/output/topology.json") as f:
            topo = json.load(f)

        edge_set = {(e["caller"], e["callee"]) for e in topo["edges"]}

        expected_edges = {
            ("api-gateway", "inventory-service"),
            ("api-gateway", "user-service"),
            ("api-gateway", "payment-service"),
        }
        assert expected_edges.issubset(edge_set), (
            f"Missing expected edges: {expected_edges - edge_set}"
        )

        for edge in topo["edges"]:
            assert isinstance(edge["call_count"], int) and edge["call_count"] > 0

    def test_topology_expected_topologies(self):
        """Expected topologies must list services present in >=80% of traces
        per route."""
        with open("/app/output/topology.json") as f:
            topo = json.load(f)

        expected = topo["expected_topologies"]
        assert isinstance(expected, dict)
        assert len(expected) > 0

        for route, services in expected.items():
            assert "api-gateway" in services, (
                f"Route {route} missing api-gateway in expected topology"
            )
            if route not in ("/health",):
                assert len(services) > 1, (
                    f"Route {route} should have downstream services"
                )

    def test_analysis_sql_executable(self):
        """analysis.sql must be valid SQL executable against telemetry.db."""
        with open("/app/output/analysis.sql") as f:
            sql_content = f.read()

        assert len(sql_content.strip()) > 0, "analysis.sql is empty"

        result = subprocess.run(
            ["sqlite3", "/app/data/telemetry.db"],
            input=sql_content,
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"SQL execution failed: {result.stderr}"
        )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) > 0, "SQL queries produced no output"

    def test_analysis_sql_contains_key_queries(self):
        """analysis.sql must contain P95 latency and topology queries."""
        with open("/app/output/analysis.sql") as f:
            sql_content = f.read().lower()

        assert "p95" in sql_content or "percentile" in sql_content or (
            "0.95" in sql_content or "95" in sql_content
        ), "analysis.sql must contain P95 latency computation"

        assert "join" in sql_content, (
            "analysis.sql must contain JOIN for topology extraction"
        )

        assert "http_route" in sql_content, (
            "analysis.sql must reference http_route"
        )
