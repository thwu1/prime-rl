#!/usr/bin/env python3
"""Critical path analyzer for microservice traces stored in SQLite.

"""

import argparse
import json
import math
import sqlite3
from collections import defaultdict


def parse_args():
    parser = argparse.ArgumentParser(
        description="Critical path analyzer for microservice traces"
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_traces(db_path):
    """Load all traces from SQLite, reconstructing span tree structures."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    trace_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT trace_id FROM spans ORDER BY trace_id")]

    traces = []
    for tid in trace_ids:
        spans = []
        for row in conn.execute(
                "SELECT * FROM spans WHERE trace_id=?", (tid,)):
            spans.append({
                "spanID": row["span_id"],
                "operationName": row["operation_name"],
                "processID": row["process_id"],
                "startTime": row["start_time_us"],
                "duration": row["duration_us"],
                "references": [],
            })

        span_by_id = {s["spanID"]: s for s in spans}
        for row in conn.execute(
                "SELECT * FROM span_references WHERE trace_id=?", (tid,)):
            sid = row["span_id"]
            if sid in span_by_id:
                span_by_id[sid]["references"].append({
                    "refType": row["ref_type"],
                    "traceID": row["parent_trace_id"],
                    "spanID": row["parent_span_id"],
                })

        processes = {}
        for row in conn.execute(
                "SELECT * FROM processes WHERE trace_id=?", (tid,)):
            processes[row["process_id"]] = {
                "serviceName": row["service_name"], "tags": []}

        traces.append({
            "traceID": tid,
            "spans": spans,
            "processes": processes,
        })

    conn.close()
    return traces


def get_service_name(trace_data, process_id):
    return trace_data["processes"].get(
        process_id, {}).get("serviceName", "unknown")


def build_span_tree(trace_data):
    """Build parent->children mapping from trace data."""
    spans_by_id = {}
    children = defaultdict(list)
    root_spans = []

    for span in trace_data["spans"]:
        sid = span["spanID"]
        spans_by_id[sid] = span

        parent_ref = None
        for ref in span.get("references", []):
            if ref.get("refType") in ("CHILD_OF", "FOLLOWS_FROM"):
                parent_ref = ref
                break

        if parent_ref:
            children[parent_ref["spanID"]].append(
                (parent_ref["refType"], span))
        else:
            root_spans.append(span)

    return spans_by_id, children, root_spans


def fix_clock_skew(span, children_map, parent_end=None):
    """Recursively adjust spans whose timing overflows their parent."""
    span_start = span["startTime"]
    span_end = span_start + span["duration"]

    if parent_end is not None:
        if span_start >= parent_end:
            span["_dropped"] = True
            return
        if span_end < span_start:
            span["_dropped"] = True
            return
        if span_end > parent_end:
            span["duration"] = parent_end - span_start
            span_end = parent_end

    span["_eff_end"] = span_start + span["duration"]

    for _ref_type, child in children_map.get(span["spanID"], []):
        fix_clock_skew(child, children_map, parent_end=span["_eff_end"])


def compute_critical_path(span, children_map, trace_data):
    """Compute the critical path via reverse walk from the span's end."""
    if span.get("_dropped"):
        return []

    span_start = span["startTime"]
    span_end = span["_eff_end"]
    service = get_service_name(trace_data, span["processID"])
    operation = span["operationName"]

    # Only CHILD_OF children participate in critical path
    child_of = []
    for ref_type, child in children_map.get(span["spanID"], []):
        if ref_type == "CHILD_OF" and not child.get("_dropped"):
            child_of.append(child)

    if not child_of:
        dur = span_end - span_start
        return [(service, operation, dur, dur)]

    child_of.sort(key=lambda c: c["_eff_end"], reverse=True)

    result = []
    current_pos = span_end
    exclusive_self = 0

    idx = 0
    while idx < len(child_of) and current_pos > span_start:
        child = child_of[idx]
        child_end = child["_eff_end"]
        child_start = child["startTime"]

        if child_end > current_pos:
            idx += 1
            continue

        gap = current_pos - child_end
        if gap > 0:
            exclusive_self += gap

        child_cp = compute_critical_path(child, children_map, trace_data)
        result.extend(child_cp)

        current_pos = child_start

        idx += 1
        while idx < len(child_of):
            if child_of[idx]["_eff_end"] <= current_pos:
                break
            idx += 1

    if current_pos > span_start:
        exclusive_self += current_pos - span_start

    inclusive_self = span_end - span_start
    result.append((service, operation, exclusive_self, inclusive_self))
    return result


def aggregate_cp_entries(fragments):
    """Aggregate CP fragments by (service, operation)."""
    by_key = defaultdict(lambda: [0, 0])
    for service, operation, excl, incl in fragments:
        by_key[(service, operation)][0] += excl
        by_key[(service, operation)][1] += incl

    entries = []
    for (service, operation), (excl, incl) in by_key.items():
        entries.append({
            "service": service,
            "operation": operation,
            "exclusive_us": excl,
            "inclusive_us": incl,
        })

    entries.sort(
        key=lambda e: (-e["exclusive_us"], e["service"], e["operation"]))
    return entries


def nearest_rank_percentile(sorted_values, p):
    """Nearest-rank ceiling percentile."""
    n = len(sorted_values)
    rank = int(math.ceil(p / 100.0 * n))
    rank = max(1, min(rank, n))
    return sorted_values[rank - 1]


def process_trace(trace_data, target_service, target_operation):
    """Process a single trace and compute its critical path."""
    _spans_by_id, children_map, root_spans = build_span_tree(trace_data)

    root = None
    for rs in root_spans:
        svc = get_service_name(trace_data, rs["processID"])
        if svc == target_service and rs["operationName"] == target_operation:
            root = rs
            break

    if root is None:
        return None

    fix_clock_skew(root, children_map)

    fragments = compute_critical_path(root, children_map, trace_data)
    cp_entries = aggregate_cp_entries(fragments)

    return {
        "trace_id": trace_data["traceID"],
        "end_to_end_us": root["_eff_end"] - root["startTime"],
        "critical_path": cp_entries,
    }


def main():
    args = parse_args()
    traces = load_traces(args.db)

    per_trace = []
    for trace_data in traces:
        result = process_trace(trace_data, args.service, args.operation)
        if result is not None:
            per_trace.append(result)

    per_trace.sort(key=lambda t: t["trace_id"])

    latency_pairs = sorted(
        [(t["end_to_end_us"], t["trace_id"]) for t in per_trace],
        key=lambda x: (x[0], x[1]),
    )

    percentiles = {}
    for label, p in [("p50", 50), ("p95", 95), ("p99", 99)]:
        lat, tid = nearest_rank_percentile(latency_pairs, p)
        percentiles[label] = {"latency_us": lat, "trace_id": tid}

    output = {
        "service": args.service,
        "operation": args.operation,
        "num_traces": len(per_trace),
        "per_trace": per_trace,
        "percentiles": percentiles,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
