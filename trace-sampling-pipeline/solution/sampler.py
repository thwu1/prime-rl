#!/usr/bin/env python3
"""Tail-based trace sampling pipeline with topology-aware adaptive thresholds.

Reads spans from /app/data/spans.jsonl, uses SQLite at /app/data/telemetry.db
for analytical queries, assembles traces, applies priority-ordered sampling
rules (including adaptive P95 latency and topology anomaly detection), enforces
fairness constraints, and writes all output artifacts.
"""

import json
import hashlib
import math
import os
import sqlite3
from collections import defaultdict

import yaml


def load_jsonl(path):
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def is_root_span(span):
    """Detect root spans across three common parent_span_id encodings."""
    parent = span.get("parent_span_id")
    if parent is None:
        return True
    if parent == "":
        return True
    if parent == "0000000000000000":
        return True
    return False


def group_traces(spans):
    traces = defaultdict(list)
    for span in spans:
        traces[span["trace_id"]].append(span)
    return dict(traces)


def get_root_span(trace_spans):
    for span in trace_spans:
        if is_root_span(span):
            return span
    return None


def compute_p95_thresholds(db_path):
    """Compute per-endpoint P95 latency thresholds from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT http_route, duration_ms
        FROM spans
        WHERE is_root = 1
        ORDER BY http_route, duration_ms
    """)

    route_durations = defaultdict(list)
    for route, duration in cursor:
        route_durations[route].append(duration)
    conn.close()

    p95 = {}
    for route, durations in route_durations.items():
        idx = min(int(len(durations) * 0.95), len(durations) - 1)
        p95[route] = durations[idx]  # already sorted by SQL ORDER BY
    return p95


def compute_topology(db_path):
    """Extract service dependency graph from SQLite database."""
    conn = sqlite3.connect(db_path)

    # All services
    services = sorted([
        row[0] for row in conn.execute(
            "SELECT DISTINCT service_name FROM spans ORDER BY service_name"
        )
    ])

    # Edges via parent-child span join
    edges = []
    for caller, callee, count in conn.execute("""
        SELECT p.service_name as caller, c.service_name as callee, COUNT(*) as cnt
        FROM spans c
        INNER JOIN spans p ON c.parent_span_id = p.span_id AND c.trace_id = p.trace_id
        WHERE c.is_root = 0
        GROUP BY p.service_name, c.service_name
        ORDER BY cnt DESC
    """):
        edges.append({"caller": caller, "callee": callee, "call_count": count})

    # Expected topologies per route (services present in >= 80% of traces)
    expected = defaultdict(list)
    for route, service, ratio in conn.execute("""
        WITH trace_routes AS (
            SELECT trace_id, http_route FROM spans WHERE is_root = 1
        ),
        trace_svcs AS (
            SELECT DISTINCT s.trace_id, r.http_route as root_route, s.service_name
            FROM spans s
            JOIN trace_routes r ON s.trace_id = r.trace_id
        ),
        route_totals AS (
            SELECT root_route, COUNT(DISTINCT trace_id) as total
            FROM trace_svcs GROUP BY root_route
        ),
        svc_presence AS (
            SELECT root_route, service_name, COUNT(DISTINCT trace_id) as present
            FROM trace_svcs GROUP BY root_route, service_name
        )
        SELECT sp.root_route, sp.service_name,
               CAST(sp.present AS FLOAT) / rt.total as presence_ratio
        FROM svc_presence sp
        JOIN route_totals rt ON sp.root_route = rt.root_route
        WHERE CAST(sp.present AS FLOAT) / rt.total >= 0.8
        ORDER BY sp.root_route, sp.service_name
    """):
        expected[route].append(service)

    conn.close()
    return services, edges, dict(expected)


def detect_topology_anomalies(traces, expected_topologies):
    """Find traces with missing expected services."""
    trace_services = defaultdict(set)
    trace_route = {}
    for tid, spans in traces.items():
        for span in spans:
            trace_services[tid].add(span.get("service_name"))
            if is_root_span(span):
                trace_route[tid] = span.get("http_route")

    anomalous = set()
    for tid, route in trace_route.items():
        expected = set(expected_topologies.get(route, []))
        actual = trace_services[tid]
        if expected - actual:
            anomalous.add(tid)
    return anomalous


def evaluate_keep_rules(trace_spans, keep_rules, p95_thresholds,
                        anomalous_traces, tid):
    """Evaluate deterministic keep rules in priority order. Returns matched
    rule name or None."""
    for rule in keep_rules:
        name = rule["name"]
        conditions = rule["match"].get("conditions", [])

        for cond in conditions:
            if "any_span_where" in cond:
                fc = cond["any_span_where"]
                field = fc["field"]
                for span in trace_spans:
                    val = span.get(field)
                    if "equals" in fc and val == fc["equals"]:
                        return name
                    if "gte" in fc and val is not None and val >= fc["gte"]:
                        return name

            elif "root_span_where" in cond:
                rc = cond["root_span_where"]
                if "adaptive_threshold" in rc:
                    at = rc["adaptive_threshold"]
                    root = get_root_span(trace_spans)
                    if root:
                        field = at["field"]
                        route = root.get("http_route")
                        val = root.get(field, 0)
                        threshold = p95_thresholds.get(route, float("inf"))
                        if val > threshold:
                            return name
                else:
                    field = rc["field"]
                    root = get_root_span(trace_spans)
                    if root:
                        val = root.get(field)
                        if "equals" in rc and val == rc["equals"]:
                            return name
                        if "gte" in rc and val is not None and val >= rc["gte"]:
                            return name
                        if "gt" in rc and val is not None and val > rc["gt"]:
                            return name

            elif "topology_anomaly" in cond:
                if tid in anomalous_traces:
                    return name

    return None


def deterministic_keep(trace_id, rate):
    """Hash-based deterministic sampling decision for reproducibility."""
    h = int(hashlib.sha256(trace_id.encode()).hexdigest(), 16)
    return (h % rate) == 0


def compute_dynamic_rates(traces_by_key, budget_remaining):
    """Compute per-key sample rates using avg_sample_rate_with_min algorithm,
    then iteratively adjust to satisfy the throughput budget."""
    if budget_remaining <= 0 or not traces_by_key:
        return {key: 999999 for key in traces_by_key}

    counts = {k: len(v) for k, v in traces_by_key.items()}
    total = sum(counts.values())
    num_keys = len(counts)

    if total <= budget_remaining:
        return {key: 1 for key in traces_by_key}

    avg_count = total / num_keys

    # Initial rates: proportional to key frequency relative to average
    rates = {}
    for key, count in counts.items():
        rates[key] = max(1, round(count / avg_count))

    # Iteratively scale rates to meet budget
    for _ in range(100):
        expected = 0
        for key, trace_ids in traces_by_key.items():
            rate = rates[key]
            for tid in trace_ids:
                if deterministic_keep(tid, rate):
                    expected += 1

        if expected <= budget_remaining:
            break

        scale = expected / budget_remaining
        any_changed = False
        for key in rates:
            new_rate = max(1, math.ceil(rates[key] * scale))
            if new_rate != rates[key]:
                any_changed = True
            rates[key] = new_rate

        if not any_changed:
            for key in rates:
                rates[key] += 1

    return rates


def write_analysis_sql(output_path):
    """Write the analytical SQL queries used for threshold computation
    and topology extraction."""
    sql = """-- Analytical queries for tail-based trace sampling pipeline
-- Execute: sqlite3 /app/data/telemetry.db < /app/output/analysis.sql

-- P95 latency thresholds per endpoint (adaptive sampling thresholds)
SELECT http_route, duration_ms as p95_threshold_ms
FROM (
    SELECT http_route, duration_ms,
           ROW_NUMBER() OVER (PARTITION BY http_route ORDER BY duration_ms) as rn,
           COUNT(*) OVER (PARTITION BY http_route) as total
    FROM spans
    WHERE is_root = 1
)
WHERE rn = CAST(total * 0.95 AS INTEGER)
ORDER BY http_route;

-- Per-service span counts and traffic distribution
SELECT service_name, COUNT(*) as span_count,
       ROUND(CAST(COUNT(*) AS FLOAT) / (SELECT COUNT(*) FROM spans) * 100, 2) as traffic_pct
FROM spans
GROUP BY service_name
ORDER BY span_count DESC;

-- Service dependency topology (caller -> callee edges via parent-child join)
SELECT p.service_name as caller, c.service_name as callee, COUNT(*) as call_count
FROM spans c
INNER JOIN spans p ON c.parent_span_id = p.span_id AND c.trace_id = p.trace_id
WHERE c.is_root = 0
GROUP BY p.service_name, c.service_name
ORDER BY call_count DESC;

-- Per-route service presence ratios for topology anomaly detection
WITH trace_routes AS (
    SELECT trace_id, http_route FROM spans WHERE is_root = 1
),
trace_svcs AS (
    SELECT DISTINCT s.trace_id, r.http_route as root_route, s.service_name
    FROM spans s
    JOIN trace_routes r ON s.trace_id = r.trace_id
),
route_totals AS (
    SELECT root_route, COUNT(DISTINCT trace_id) as total
    FROM trace_svcs GROUP BY root_route
),
svc_presence AS (
    SELECT root_route, service_name, COUNT(DISTINCT trace_id) as present
    FROM trace_svcs GROUP BY root_route, service_name
)
SELECT sp.root_route, sp.service_name, sp.present, rt.total,
       ROUND(CAST(sp.present AS FLOAT) / rt.total, 4) as presence_ratio
FROM svc_presence sp
JOIN route_totals rt ON sp.root_route = rt.root_route
ORDER BY sp.root_route, presence_ratio DESC;
"""
    with open(output_path, "w") as f:
        f.write(sql)


def main():
    # Load configurations
    with open("/app/config/rules.yaml") as f:
        config = yaml.safe_load(f)

    with open("/app/config/slos.yaml") as f:
        slo_config = yaml.safe_load(f)

    db_path = "/app/data/telemetry.db"

    # Load and assemble traces
    spans = load_jsonl("/app/data/spans.jsonl")
    traces = group_traces(spans)

    budget = config["budget"]["max_output_traces"]

    # Compute adaptive P95 thresholds from SQLite
    p95_thresholds = compute_p95_thresholds(db_path)
    print("P95 latency thresholds per endpoint:")
    for route, val in sorted(p95_thresholds.items()):
        print(f"  {route}: {val:.2f}ms")

    # Build service topology from SQLite
    services, edges, expected_topologies = compute_topology(db_path)
    print(f"\nTopology: {len(services)} services, {len(edges)} edges")
    for route, svcs in sorted(expected_topologies.items()):
        print(f"  {route}: {svcs}")

    # Detect topology anomalies
    anomalous_traces = detect_topology_anomalies(traces, expected_topologies)
    print(f"\nAnomalous traces (missing expected services): {len(anomalous_traces)}")

    # Parse rules
    rules = sorted(config["rules"], key=lambda r: r["priority"])
    keep_rules = [r for r in rules if r["decision"]["action"] == "keep"]
    sample_rules = [r for r in rules if r["decision"].get("action") == "sample"]

    # Phase 1: Apply deterministic keep rules in priority order
    must_keep = {}  # trace_id -> rule_name
    dynamic_pool = []  # trace_ids for dynamic sampling

    for tid, trace_spans in traces.items():
        matched = evaluate_keep_rules(
            trace_spans, keep_rules, p95_thresholds, anomalous_traces, tid
        )
        if matched:
            must_keep[tid] = matched
        else:
            dynamic_pool.append(tid)

    print(f"\nMust-keep traces: {len(must_keep)}")
    rule_counts = defaultdict(int)
    for r in must_keep.values():
        rule_counts[r] += 1
    for r, c in sorted(rule_counts.items()):
        print(f"  {r}: {c}")

    # Phase 2: Dynamic sampling with budget enforcement
    budget_remaining = budget - len(must_keep)

    dynamic_rule = sample_rules[0] if sample_rules else None
    key_fields = (
        dynamic_rule["decision"]["key_fields"]
        if dynamic_rule
        else ["service_name"]
    )

    traces_by_key = defaultdict(list)
    for tid in dynamic_pool:
        root = get_root_span(traces[tid])
        if root is not None:
            key = tuple(str(root.get(f, "unknown")) for f in key_fields)
        else:
            key = ("unknown",) * len(key_fields)
        traces_by_key[key].append(tid)

    rates = compute_dynamic_rates(dict(traces_by_key), budget_remaining)

    dynamic_kept = {}  # trace_id -> (rate, rule_name)
    rule_name = dynamic_rule["name"] if dynamic_rule else "default-sample"
    for key, trace_ids in traces_by_key.items():
        rate = rates[key]
        for tid in trace_ids:
            if deterministic_keep(tid, rate):
                dynamic_kept[tid] = (rate, rule_name)

    # Phase 3: Fairness enforcement
    all_pairs = set()
    for span in spans:
        svc = span.get("service_name")
        route = span.get("http_route")
        if svc and route:
            all_pairs.add((svc, route))

    sampled_pairs = set()
    for tid in list(must_keep.keys()) + list(dynamic_kept.keys()):
        for span in traces[tid]:
            svc = span.get("service_name")
            route = span.get("http_route")
            if svc and route:
                sampled_pairs.add((svc, route))

    missing_pairs = all_pairs - sampled_pairs
    current_total = len(must_keep) + len(dynamic_kept)
    for pair in missing_pairs:
        if current_total >= budget:
            break
        svc, route = pair
        found = False
        for tid in dynamic_pool:
            if tid not in dynamic_kept and not found:
                for span in traces[tid]:
                    if (span.get("service_name") == svc
                            and span.get("http_route") == route):
                        dynamic_kept[tid] = (1, "fairness-override")
                        current_total += 1
                        found = True
                        break
            if found:
                break

    # Phase 4: Assemble output spans with annotations
    os.makedirs("/app/output", exist_ok=True)

    output_spans = []
    for tid, matched_rule in must_keep.items():
        for span in traces[tid]:
            annotated = dict(span)
            annotated["meta_sample_rate"] = 1
            annotated["meta_rule"] = matched_rule
            output_spans.append(annotated)

    for tid, (rate, matched_rule) in dynamic_kept.items():
        for span in traces[tid]:
            annotated = dict(span)
            annotated["meta_sample_rate"] = rate
            annotated["meta_rule"] = matched_rule
            output_spans.append(annotated)

    with open("/app/output/sampled_spans.jsonl", "w") as f:
        for span in output_spans:
            f.write(json.dumps(span) + "\n")

    # Phase 5: Generate sampling report
    rules_breakdown = defaultdict(int)
    for matched_rule in must_keep.values():
        rules_breakdown[matched_rule] += 1
    for rate, matched_rule in dynamic_kept.values():
        rules_breakdown[matched_rule] += 1

    effective_rates = {}
    for key, trace_ids in traces_by_key.items():
        kept_count = sum(1 for tid in trace_ids if tid in dynamic_kept)
        key_str = "|".join(key)
        effective_rates[key_str] = {
            "total": len(trace_ids),
            "kept": kept_count,
            "configured_rate": rates[key],
        }

    total_kept = len(must_keep) + len(dynamic_kept)
    report = {
        "total_traces": len(traces),
        "kept_traces": total_kept,
        "rules_breakdown": dict(rules_breakdown),
        "effective_rates": effective_rates,
    }
    with open("/app/output/sampling_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Phase 6: Write topology output
    with open("/app/output/topology.json", "w") as f:
        json.dump({
            "services": services,
            "edges": edges,
            "expected_topologies": {
                k: sorted(v) for k, v in expected_topologies.items()
            },
        }, f, indent=2)

    # Phase 7: Write analysis SQL
    write_analysis_sql("/app/output/analysis.sql")

    # Phase 8: Compute SLO report
    slo_results = []
    for slo_def in slo_config["slos"]:
        service = slo_def["service"]
        slo_type = slo_def["type"]
        target = slo_def["target"]

        raw_root_spans = [
            s for s in spans
            if is_root_span(s) and s.get("service_name") == service
        ]

        if slo_type == "availability":
            threshold_val = slo_def["sli"]["good_event"]["value"]

            raw_good = sum(
                1 for s in raw_root_spans
                if s.get("http_status_code", 0) < threshold_val
            )
            raw_total = len(raw_root_spans)
            raw_sli = raw_good / raw_total if raw_total > 0 else 1.0

            sampled_root = [
                s for s in output_spans
                if is_root_span(s) and s.get("service_name") == service
            ]
            weighted_good = sum(
                s["meta_sample_rate"]
                for s in sampled_root
                if s.get("http_status_code", 0) < threshold_val
            )
            weighted_total = sum(s["meta_sample_rate"] for s in sampled_root)
            sampled_sli = (
                weighted_good / weighted_total if weighted_total > 0 else 1.0
            )

        elif slo_type == "latency":
            threshold_ms = slo_def["sli"]["threshold_ms"]
            latency_field = slo_def["sli"]["latency_field"]

            raw_under = sum(
                1 for s in raw_root_spans
                if s.get(latency_field, 0) <= threshold_ms
            )
            raw_total = len(raw_root_spans)
            raw_sli = raw_under / raw_total if raw_total > 0 else 1.0

            sampled_root = [
                s for s in output_spans
                if is_root_span(s) and s.get("service_name") == service
            ]
            weighted_under = sum(
                s["meta_sample_rate"]
                for s in sampled_root
                if s.get(latency_field, 0) <= threshold_ms
            )
            weighted_total = sum(s["meta_sample_rate"] for s in sampled_root)
            sampled_sli = (
                weighted_under / weighted_total if weighted_total > 0 else 1.0
            )
        else:
            continue

        slo_results.append({
            "name": slo_def["name"],
            "service": service,
            "type": slo_type,
            "target": target,
            "raw_sli": round(raw_sli, 6),
            "sampled_sli": round(sampled_sli, 6),
            "meets_target": raw_sli >= target,
        })

    with open("/app/output/slo_report.json", "w") as f:
        json.dump({"slos": slo_results}, f, indent=2)

    print(f"\nSampling complete: {len(traces)} traces -> {total_kept} kept")
    print(f"  Must-keep: {len(must_keep)}, Dynamic: {len(dynamic_kept)}")
    print(f"  Budget: {budget}, Used: {total_kept}")


if __name__ == "__main__":
    main()
