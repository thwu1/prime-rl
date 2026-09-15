#!/usr/bin/env python3
"""Generate synthetic Jaeger trace files for CRISP analyzer task.

"""

import json
import os

BASE = 1700000000000000  # base timestamp in microseconds


def make_span(trace_id, span_id, operation, process_id, start_offset, duration,
              parent_span_id=None, ref_type="CHILD_OF"):
    span = {
        "traceID": trace_id,
        "spanID": span_id,
        "flags": 1,
        "operationName": operation,
        "references": [],
        "startTime": BASE + start_offset,
        "duration": duration,
        "tags": [],
        "logs": [],
        "processID": process_id,
        "warnings": None
    }
    if parent_span_id:
        span["references"] = [{
            "refType": ref_type,
            "traceID": trace_id,
            "spanID": parent_span_id
        }]
    return span


def make_trace_file(trace_id, spans, processes):
    return {
        "data": [{
            "traceID": trace_id,
            "spans": spans,
            "processes": {
                pid: {"serviceName": svc, "tags": []}
                for pid, svc in processes.items()
            },
            "warnings": None
        }],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "errors": None
    }


def write_trace(output_dir, filename, trace_data):
    with open(os.path.join(output_dir, filename), "w") as f:
        json.dump(trace_data, f, indent=2)


def generate_all(output_dir):
    os.makedirs(output_dir, exist_ok=True)

    # Trace 1 (t001): Linear chain A->B->C, 100ms
    spans = [
        make_span("t001", "s1a", "handleRequest", "p1", 0, 100000),
        make_span("t001", "s1b", "validate", "p2", 10000, 30000, "s1a"),
        make_span("t001", "s1c", "lookup", "p3", 15000, 20000, "s1b"),
    ]
    t = make_trace_file("t001", spans,
                        {"p1": "gateway", "p2": "auth", "p3": "userdb"})
    write_trace(output_dir, "trace_001.json", t)

    # Trace 2 (t002): Parallel spans, 200ms
    spans = [
        make_span("t002", "s2a", "handleRequest", "p1", 0, 200000),
        make_span("t002", "s2b", "fetch", "p2", 20000, 60000, "s2a"),
        make_span("t002", "s2c", "fetch", "p3", 30000, 150000, "s2a"),
    ]
    t = make_trace_file("t002", spans,
                        {"p1": "gateway", "p2": "serviceA", "p3": "serviceB"})
    write_trace(output_dir, "trace_002.json", t)

    # Trace 3 (t003): Clock skew overflow, 100ms
    # Spans are intentionally shuffled (not parent-first order)
    spans = [
        make_span("t003", "s3c", "query", "p3", 20000, 85000, "s3b"),
        make_span("t003", "s3a", "handleRequest", "p1", 0, 100000),
        make_span("t003", "s3b", "process", "p2", 10000, 110000, "s3a"),
    ]
    t = make_trace_file("t003", spans,
                        {"p1": "gateway", "p2": "backend", "p3": "db"})
    write_trace(output_dir, "trace_003.json", t)

    # Trace 4 (t004): FOLLOWS_FROM exclusion, 150ms
    # Root span is NOT first in array
    spans = [
        make_span("t004", "s4d", "process", "p4", 60000, 70000, "s4a"),
        make_span("t004", "s4b", "log", "p2", 5000, 80000, "s4a", "FOLLOWS_FROM"),
        make_span("t004", "s4a", "handleRequest", "p1", 0, 150000),
        make_span("t004", "s4c", "validate", "p3", 10000, 40000, "s4a"),
    ]
    t = make_trace_file("t004", spans,
                        {"p1": "gateway", "p2": "analytics", "p3": "auth",
                         "p4": "backend"})
    write_trace(output_dir, "trace_004.json", t)

    # Trace 5 (t005): Deep 5-level nesting, 300ms
    # Spans in shuffled order
    spans = [
        make_span("t005", "s5d", "call", "p4", 150000, 120000, "s5b"),
        make_span("t005", "s5f", "compute", "p6", 160000, 90000, "s5d"),
        make_span("t005", "s5a", "handleRequest", "p1", 0, 300000),
        make_span("t005", "s5e", "query", "p5", 30000, 80000, "s5c"),
        make_span("t005", "s5c", "call", "p3", 20000, 100000, "s5b"),
        make_span("t005", "s5b", "process", "p2", 10000, 280000, "s5a"),
    ]
    t = make_trace_file("t005", spans,
                        {"p1": "gateway", "p2": "serviceA", "p3": "serviceB",
                         "p4": "serviceD", "p5": "serviceC", "p6": "serviceE"})
    write_trace(output_dir, "trace_005.json", t)

    # Trace 6 (t006): Simple two-level, 120ms
    spans = [
        make_span("t006", "s6a", "handleRequest", "p1", 0, 120000),
        make_span("t006", "s6b", "process", "p2", 15000, 90000, "s6a"),
    ]
    t = make_trace_file("t006", spans,
                        {"p1": "gateway", "p2": "backend"})
    write_trace(output_dir, "trace_006.json", t)

    # Trace 7 (t007): Three sequential children, 140ms
    spans = [
        make_span("t007", "s7a", "handleRequest", "p1", 0, 140000),
        make_span("t007", "s7b", "validate", "p2", 10000, 30000, "s7a"),
        make_span("t007", "s7c", "process", "p3", 50000, 70000, "s7a"),
    ]
    t = make_trace_file("t007", spans,
                        {"p1": "gateway", "p2": "auth", "p3": "backend"})
    write_trace(output_dir, "trace_007.json", t)

    # Trace 8 (t008): Single child, 160ms
    spans = [
        make_span("t008", "s8a", "handleRequest", "p1", 0, 160000),
        make_span("t008", "s8b", "process", "p2", 25000, 110000, "s8a"),
    ]
    t = make_trace_file("t008", spans,
                        {"p1": "gateway", "p2": "backend"})
    write_trace(output_dir, "trace_008.json", t)

    # Trace 9 (t009): Three sequential children, 180ms
    spans = [
        make_span("t009", "s9a", "handleRequest", "p1", 0, 180000),
        make_span("t009", "s9b", "validate", "p2", 15000, 50000, "s9a"),
        make_span("t009", "s9c", "process", "p3", 70000, 100000, "s9a"),
    ]
    t = make_trace_file("t009", spans,
                        {"p1": "gateway", "p2": "auth", "p3": "backend"})
    write_trace(output_dir, "trace_009.json", t)

    # Trace 10 (t010): Single child long, 250ms
    spans = [
        make_span("t010", "s10a", "handleRequest", "p1", 0, 250000),
        make_span("t010", "s10b", "process", "p2", 40000, 170000, "s10a"),
    ]
    t = make_trace_file("t010", spans,
                        {"p1": "gateway", "p2": "backend"})
    write_trace(output_dir, "trace_010.json", t)


if __name__ == "__main__":
    generate_all("/app/traces")
