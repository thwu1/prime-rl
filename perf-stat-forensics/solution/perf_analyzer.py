#!/usr/bin/env python3
"""
Performance incident triage analyzer.

Parses perf stat hardware counter captures and folded stack traces,
applies config-driven bottleneck classification and regression detection,
and generates a differential flame graph SVG.
"""

import json
import os
import re
import subprocess
from collections import defaultdict

CAPTURES_DIR = "/app/captures"
CONFIG_FILE = "/app/config/thresholds.json"
OUTPUT_FILE = "/app/analysis_report.json"
FLAMEGRAPH_DIR = "/app/FlameGraph"
SVG_OUTPUT = "/app/diff_flamegraph.svg"

WORKLOADS = ["matrix_multiply", "sort_benchmark", "web_server"]
CONFIGS = ["baseline", "modified"]


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def parse_perfstat(filepath):
    """Parse a perf stat output file. Returns (counters dict, elapsed_time).

    Handles:
    - Comma-separated counter values (e.g. 4,000,000,000)
    - <not supported> events (stored as None)
    - Various annotation styles (# comments after values)
    - Elapsed time extraction
    """
    counters = {}
    elapsed_time = None

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            # Match elapsed time line
            m = re.match(r"([\d.]+)\s+seconds time elapsed", stripped)
            if m:
                elapsed_time = float(m.group(1))
                continue

            # Handle <not supported> events
            if "<not supported>" in stripped:
                m = re.match(r"<not supported>\s+([\w-]+)", stripped)
                if m:
                    counters[m.group(1)] = None
                continue

            # Match counter lines: value event-name # annotation
            m = re.match(r"([\d,]+)\s+([\w-]+)", stripped)
            if m:
                value_str = m.group(1)
                event = m.group(2)
                counters[event] = int(value_str.replace(",", ""))

    return counters, elapsed_time


def compute_metrics(counters):
    """Derive standard PMC metrics from raw hardware counter values."""
    cycles = counters.get("cycles")
    instructions = counters.get("instructions")
    cache_refs = counters.get("cache-references")
    cache_misses = counters.get("cache-misses")
    branch_instr = counters.get("branch-instructions")
    branch_misses = counters.get("branch-misses")
    stall_fe = counters.get("stalled-cycles-frontend")
    stall_be = counters.get("stalled-cycles-backend")

    metrics = {}

    # IPC: instructions per cycle
    if cycles and instructions:
        metrics["ipc"] = instructions / cycles
    else:
        metrics["ipc"] = None

    # Cache miss rate: fraction of cache references that missed
    if cache_refs and cache_misses is not None:
        metrics["cache_miss_rate"] = cache_misses / cache_refs
    else:
        metrics["cache_miss_rate"] = None

    # Branch miss rate: fraction of branches that mispredicted
    if branch_instr and branch_misses is not None:
        metrics["branch_miss_rate"] = branch_misses / branch_instr
    else:
        metrics["branch_miss_rate"] = None

    # Frontend stall ratio: fraction of cycles stalled in frontend
    if stall_fe is not None and cycles:
        metrics["frontend_stall_ratio"] = stall_fe / cycles
    else:
        metrics["frontend_stall_ratio"] = None

    # Backend stall ratio: fraction of cycles stalled in backend
    if stall_be is not None and cycles:
        metrics["backend_stall_ratio"] = stall_be / cycles
    else:
        metrics["backend_stall_ratio"] = None

    return metrics


def evaluate_rule(metrics, conditions):
    """Evaluate a list of threshold conditions against computed metrics.

    All conditions must be satisfied (conjunction). If any referenced
    metric is null, the rule cannot match.
    """
    for cond in conditions:
        value = metrics.get(cond["metric"])
        if value is None:
            return False
        op = cond["op"]
        threshold = cond["value"]
        if op == "<" and not (value < threshold):
            return False
        elif op == ">=" and not (value >= threshold):
            return False
        elif op == "<=" and not (value <= threshold):
            return False
        elif op == ">" and not (value > threshold):
            return False
    return True


def classify(metrics, config):
    """Classify workload bottleneck using priority-ordered rules from config."""
    cls_config = config["classification"]
    for category in cls_config["priority_order"]:
        conditions = cls_config["rules"][category]
        if evaluate_rule(metrics, conditions):
            return category
    return cls_config["default"]


def detect_regression(baseline_metrics, modified_metrics, config):
    """Detect performance regression between baseline and modified configurations."""
    reg_config = config["regression"]
    b_ipc = baseline_metrics["ipc"]
    m_ipc = modified_metrics["ipc"]

    if b_ipc is None or m_ipc is None or b_ipc == 0:
        return {
            "detected": False, "ipc_delta": None,
            "primary_cause": "none", "severity": "none",
        }

    ipc_delta = m_ipc - b_ipc
    relative_decrease = (b_ipc - m_ipc) / b_ipc
    detected = relative_decrease >= reg_config["min_relative_ipc_decrease"]

    if not detected:
        return {
            "detected": False, "ipc_delta": ipc_delta,
            "primary_cause": "none", "severity": "none",
        }

    # Determine primary cause: metric with the largest relative increase
    cause_labels = reg_config["cause_labels"]
    max_rel_increase = -float("inf")
    primary_cause = "none"

    for metric, label in cause_labels.items():
        b_val = baseline_metrics.get(metric)
        m_val = modified_metrics.get(metric)
        if b_val is None or m_val is None:
            continue
        if b_val > 0:
            rel_increase = (m_val - b_val) / b_val
        elif m_val > 0:
            rel_increase = float("inf")
        else:
            continue

        if rel_increase > max_rel_increase:
            max_rel_increase = rel_increase
            primary_cause = label

    # Determine severity from config thresholds
    sev_config = reg_config["severity"]
    if ipc_delta <= sev_config["critical_max_delta"]:
        severity = "critical"
    elif ipc_delta <= sev_config["moderate_max_delta"]:
        severity = "moderate"
    else:
        severity = "minor"

    return {
        "detected": True,
        "ipc_delta": ipc_delta,
        "primary_cause": primary_cause,
        "severity": severity,
    }


def parse_folded(filepath):
    """Parse folded stack trace file.

    Format: func1;func2;...;funcN count
    Returns list of (function_list, count).
    """
    stacks = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            stack_str, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            stacks.append((stack_str.split(";"), count))
    return stacks


def compute_stack_metrics(stacks):
    """Compute exclusive (self) and inclusive counts per function.

    Exclusive: samples where the function is the leaf (rightmost in stack).
    Inclusive: samples where the function appears anywhere in the stack.
    """
    exclusive = defaultdict(int)
    inclusive = defaultdict(int)
    total = 0

    for functions, count in stacks:
        total += count
        # Exclusive: leaf function only
        exclusive[functions[-1]] += count
        # Inclusive: each unique function in the stack
        seen = set()
        for func in functions:
            if func not in seen:
                inclusive[func] += count
                seen.add(func)

    return exclusive, inclusive, total


def analyze_stacks(baseline_path, modified_path):
    """Differential stack analysis between baseline and modified profiles."""
    b_stacks = parse_folded(baseline_path)
    m_stacks = parse_folded(modified_path)

    b_excl, b_incl, b_total = compute_stack_metrics(b_stacks)
    m_excl, m_incl, m_total = compute_stack_metrics(m_stacks)

    # Compute exclusive percentages for each profile
    b_pcts = {f: (c / b_total) * 100 for f, c in b_excl.items()} if b_total else {}
    m_pcts = {f: (c / m_total) * 100 for f, c in m_excl.items()} if m_total else {}
    m_incl_pcts = {f: (c / m_total) * 100 for f, c in m_incl.items()} if m_total else {}

    # Top regressions: functions with largest increase in exclusive %
    all_functions = set(b_pcts.keys()) | set(m_pcts.keys())
    regressions = []
    for func in all_functions:
        b_pct = b_pcts.get(func, 0.0)
        m_pct = m_pcts.get(func, 0.0)
        delta = m_pct - b_pct
        if delta > 0:
            regressions.append({
                "function": func,
                "baseline_pct": round(b_pct, 2),
                "modified_pct": round(m_pct, 2),
                "delta": round(delta, 2),
            })
    regressions.sort(key=lambda x: x["delta"], reverse=True)
    top_regressions = regressions[:5]

    # Top consumers in modified profile by exclusive %
    consumers = []
    for func in sorted(m_pcts, key=m_pcts.get, reverse=True)[:5]:
        consumers.append({
            "function": func,
            "exclusive_pct": round(m_pcts[func], 2),
            "inclusive_pct": round(m_incl_pcts.get(func, m_pcts[func]), 2),
        })

    return {
        "top_regressions": top_regressions,
        "top_consumers_modified": consumers,
    }


def validate_workload(counters, elapsed_time, config):
    """Check system-level validation flags from modified config event rates."""
    val_config = config["validation"]
    cs = counters.get("context-switches") or 0
    mig = counters.get("cpu-migrations") or 0
    elapsed = elapsed_time if elapsed_time and elapsed_time > 0 else 1.0

    return {
        "noisy_system": (cs / elapsed) > val_config["noisy_ctx_switches_per_sec"],
        "migration_issues": (mig / elapsed) > val_config["migration_per_sec"],
    }


def generate_diff_flamegraph():
    """Generate differential flame graph SVG using FlameGraph tools."""
    baseline = os.path.join(CAPTURES_DIR, "matrix_multiply_baseline.folded")
    modified = os.path.join(CAPTURES_DIR, "matrix_multiply_modified.folded")
    difffolded = os.path.join(FLAMEGRAPH_DIR, "difffolded.pl")
    flamegraph = os.path.join(FLAMEGRAPH_DIR, "flamegraph.pl")

    # difffolded.pl produces differential folded stacks
    diff_proc = subprocess.run(
        ["perl", difffolded, baseline, modified],
        capture_output=True, text=True,
    )

    # flamegraph.pl renders them as an interactive SVG
    svg_proc = subprocess.run(
        ["perl", flamegraph],
        input=diff_proc.stdout,
        capture_output=True, text=True,
    )

    with open(SVG_OUTPUT, "w") as f:
        f.write(svg_proc.stdout)

    print(f"Differential flame graph written to {SVG_OUTPUT}")


def main():
    config = load_config()
    report = {"workloads": {}, "stack_analysis": {}, "validation": {}}

    for workload in WORKLOADS:
        configs_data = {}
        workload_entry = {}

        for cfg in CONFIGS:
            path = os.path.join(CAPTURES_DIR, f"{workload}_{cfg}.perfstat")
            counters, elapsed = parse_perfstat(path)
            metrics = compute_metrics(counters)
            classification = classify(metrics, config)

            configs_data[cfg] = {
                "counters": counters,
                "elapsed": elapsed,
                "metrics": metrics,
            }

            workload_entry[cfg] = {
                "ipc": metrics["ipc"],
                "cache_miss_rate": metrics["cache_miss_rate"],
                "branch_miss_rate": metrics["branch_miss_rate"],
                "frontend_stall_ratio": metrics["frontend_stall_ratio"],
                "backend_stall_ratio": metrics["backend_stall_ratio"],
                "classification": classification,
            }

        # Regression detection
        workload_entry["regression"] = detect_regression(
            configs_data["baseline"]["metrics"],
            configs_data["modified"]["metrics"],
            config,
        )
        report["workloads"][workload] = workload_entry

        # Validation from modified config
        report["validation"][workload] = validate_workload(
            configs_data["modified"]["counters"],
            configs_data["modified"]["elapsed"],
            config,
        )

    # Stack analysis for matrix_multiply
    b_folded = os.path.join(CAPTURES_DIR, "matrix_multiply_baseline.folded")
    m_folded = os.path.join(CAPTURES_DIR, "matrix_multiply_modified.folded")
    if os.path.exists(b_folded) and os.path.exists(m_folded):
        report["stack_analysis"]["matrix_multiply"] = analyze_stacks(
            b_folded, m_folded,
        )

    with open(OUTPUT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {OUTPUT_FILE}")

    # Generate differential flame graph
    generate_diff_flamegraph()


if __name__ == "__main__":
    main()
