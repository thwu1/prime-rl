#!/usr/bin/env python3
"""Analyzer: builds computation graphs and writes results.json."""

import json
import sys
sys.path.insert(0, "/app")
from graph_utils import build_graph, compute_work, compute_span, detect_races, load_trace


def analyze_trace(path):
    program = load_trace(path)
    steps, edges = build_graph(program)
    work = compute_work(steps)
    span = compute_span(steps, edges)
    par = work / span if span > 0 else 0.0
    races = detect_races(steps, edges)
    return {
        "num_steps": len(steps),
        "num_edges": len(edges),
        "work": work,
        "span": span,
        "parallelism": par,
        "data_races": races,
    }


def main():
    results = {}
    for i in range(1, 7):
        results[f"trace{i}"] = analyze_trace(f"/app/traces/trace{i}.json")
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
