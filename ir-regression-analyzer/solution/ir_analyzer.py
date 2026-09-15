#!/usr/bin/env python3
"""LLVM IR Optimization Regression Analyzer.

Parses LLVM IR (.ll) files to extract per-function instruction counts,
compares baseline vs patched versions, and produces a regression report.
"""

import json
import math
import os
import re
import sys

# Regex to match a function definition line (captures the @name)
FUNC_DEF_RE = re.compile(
    r'^define\b.*?(@(?:"[^"]+"|[-a-zA-Z$._0-9]+))\s*\('
)

# Regex to match a basic block label line (after stripping comments)
LABEL_RE = re.compile(
    r'^(?:[a-zA-Z$._][-a-zA-Z$._0-9]*|\d+|"[^"]*"):\s*$'
)


def strip_comment(line):
    """Remove trailing ; comment from a line, respecting string literals."""
    # Simple approach: find first ; that's not inside a string constant
    in_string = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_string = not in_string
        elif ch == ';' and not in_string:
            return line[:i].rstrip()
    return line


def parse_ll_file(filepath):
    """Parse an LLVM IR file. Returns dict mapping function name -> instruction count."""
    functions = {}

    with open(filepath, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\n')
        m = FUNC_DEF_RE.match(line)
        if m:
            func_name = m.group(1)
            # The opening { should be on this line
            # Move to the next line to start counting body instructions
            i += 1
            count = 0
            while i < len(lines):
                body_line = lines[i].rstrip('\n')
                stripped = body_line.strip()

                # End of function
                if stripped == '}':
                    break

                # Skip empty lines
                if not stripped:
                    i += 1
                    continue

                # Skip pure comment lines
                if stripped.startswith(';'):
                    i += 1
                    continue

                # Strip inline comments for label detection
                code = strip_comment(stripped)
                if not code:
                    i += 1
                    continue

                # Check if it's a basic block label
                if LABEL_RE.match(code):
                    i += 1
                    continue

                # Everything else is an instruction
                count += 1
                i += 1

            functions[func_name] = count
        i += 1

    return functions


def scan_directory(dirpath):
    """Scan all .ll files in a directory and return combined function dict."""
    all_functions = {}
    for filename in sorted(os.listdir(dirpath)):
        if filename.endswith('.ll'):
            filepath = os.path.join(dirpath, filename)
            file_functions = parse_ll_file(filepath)
            all_functions.update(file_functions)
    return all_functions


def analyze(baseline_dir, patched_dir, output_path):
    baseline_funcs = scan_directory(baseline_dir)
    patched_funcs = scan_directory(patched_dir)

    baseline_names = set(baseline_funcs.keys())
    patched_names = set(patched_funcs.keys())

    matched_names = baseline_names & patched_names
    deleted_names = baseline_names - patched_names
    added_names = patched_names - baseline_names

    # Total instructions (all functions, including unmatched)
    total_baseline = sum(baseline_funcs.values())
    total_patched = sum(patched_funcs.values())
    total_delta = total_patched - total_baseline

    # Per-function analysis for matched functions
    THRESHOLD = 0.00001
    changed = []
    improved = []
    regressed = []

    for name in matched_names:
        b = baseline_funcs[name]
        p = patched_funcs[name]
        if b == p:
            continue
        delta_pct = (p - b) / b if b != 0 else 0.0
        if abs(delta_pct) < THRESHOLD:
            continue
        entry = {
            "function": name,
            "baseline": b,
            "patched": p,
            "delta_pct": delta_pct,
        }
        changed.append(entry)
        if delta_pct < 0:
            improved.append(entry)
        else:
            regressed.append(entry)

    # Sort: improvements ascending (most negative first), regressions descending
    improved.sort(key=lambda x: x["delta_pct"])
    regressed.sort(key=lambda x: x["delta_pct"], reverse=True)

    # Geometric mean
    if changed:
        log_sum = sum(
            math.log(e["patched"] / e["baseline"])
            for e in changed
            if e["baseline"] > 0 and e["patched"] > 0
        )
        geomean = math.exp(log_sum / len(changed)) - 1
    else:
        geomean = 0.0

    # Verdict
    if geomean < -0.001:
        verdict = "improvement"
    elif geomean > 0.001:
        verdict = "regression"
    else:
        verdict = "neutral"

    # Build result
    result = {
        "total_baseline_instructions": total_baseline,
        "total_patched_instructions": total_patched,
        "total_delta": total_delta,
        "num_matched_functions": len(matched_names),
        "num_changed_functions": len(changed),
        "num_improved_functions": len(improved),
        "num_regressed_functions": len(regressed),
        "num_deleted_functions": len(deleted_names),
        "num_added_functions": len(added_names),
        "geometric_mean_change": round(geomean, 6),
        "top_improvements": [
            {
                "function": e["function"],
                "baseline": e["baseline"],
                "patched": e["patched"],
                "delta_pct": round(e["delta_pct"], 6),
            }
            for e in improved[:10]
        ],
        "top_regressions": [
            {
                "function": e["function"],
                "baseline": e["baseline"],
                "patched": e["patched"],
                "delta_pct": round(e["delta_pct"], 6),
            }
            for e in regressed[:10]
        ],
        "verdict": verdict,
    }

    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Report written to {output_path}")
    print(f"Verdict: {verdict}")
    print(f"Delta: {total_delta} instructions ({geomean:+.4%} geometric mean)")


if __name__ == "__main__":
    analyze(
        "/app/corpus/baseline",
        "/app/corpus/patched",
        "/app/results.json",
    )
