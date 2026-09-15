#!/usr/bin/env python3
"""

Parse a cachegrind output file (.out) and extract key metrics as JSON.
Reads the structured output file directly (events: / summary: lines),
which is far more robust than regex-matching stderr text.

Usage: parse_cachegrind.py <cachegrind_output_file>
"""
import sys
import json


def parse_cachegrind_outfile(filepath):
    """Extract cache metrics from a cachegrind .out file."""
    events = []
    summary_vals = []

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("events:"):
                events = line.split(":", 1)[1].strip().split()
            elif line.startswith("summary:"):
                summary_vals = [int(x) for x in line.split(":", 1)[1].strip().split()]

    if not events or not summary_vals or len(events) != len(summary_vals):
        return {"I_refs": 0, "D_refs": 0, "D1_misses": 0, "LLd_misses": 0}

    event_map = dict(zip(events, summary_vals))

    metrics = {
        "I_refs": event_map.get("Ir", 0),
        "D_refs": event_map.get("Dr", 0) + event_map.get("Dw", 0),
        "D1_misses": event_map.get("D1mr", 0) + event_map.get("D1mw", 0),
        "LLd_misses": event_map.get("DLmr", 0) + event_map.get("DLmw", 0),
    }
    return metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: parse_cachegrind.py <cachegrind_output_file>", file=sys.stderr)
        sys.exit(1)

    metrics = parse_cachegrind_outfile(sys.argv[1])
    json.dump(metrics, sys.stdout, indent=2)
    sys.stdout.write("\n")
