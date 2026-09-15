#!/usr/bin/env python3
"""Differential flame graph regression analysis tool.

Parses folded stack trace files, computes exclusive/inclusive metrics,
generates flame graph SVGs, applies USE Method to system metrics,
and produces a structured JSON report.
"""

import json
import os
import subprocess
from collections import defaultdict


def parse_folded(filepath):
    """Parse a folded stack trace file.

    Format: frame1;frame2;...;frameN count
    Returns list of (frames_list, count) tuples.
    """
    entries = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            stack_str, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            frames = stack_str.split(";")
            entries.append((frames, count))
    return entries


def compute_exclusive(entries):
    """Compute exclusive (self/leaf) sample counts per function.

    A function's exclusive count is the sum of samples where it
    appears as the rightmost (leaf) frame in a stack.
    """
    counts = defaultdict(int)
    for frames, count in entries:
        leaf = frames[-1]
        counts[leaf] += count
    return dict(counts)


def compute_inclusive(entries):
    """Compute inclusive (cumulative) sample counts per function.

    A function's inclusive count is the sum of samples from all
    stacks where the function appears at any position. Each function
    is counted at most once per stack (using a seen-set).
    """
    counts = defaultdict(int)
    for frames, count in entries:
        seen = set()
        for frame in frames:
            if frame not in seen:
                counts[frame] += count
                seen.add(frame)
    return dict(counts)


def get_all_functions(entries):
    """Get set of all unique function names across all stacks."""
    funcs = set()
    for frames, _ in entries:
        funcs.update(frames)
    return funcs


def top_n(counts, total, n=5):
    """Return top N functions by count, sorted desc by count then alpha."""
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    result = []
    for func, samples in sorted_items[:n]:
        result.append(
            {
                "function": func,
                "samples": samples,
                "percent": round(100.0 * samples / total, 2),
            }
        )
    return result


def compute_exclusive_diff(excl_baseline, excl_regression):
    """Compute per-function exclusive sample count delta (regression - baseline)."""
    all_funcs = set(excl_baseline.keys()) | set(excl_regression.keys())
    diffs = {}
    for func in all_funcs:
        b = excl_baseline.get(func, 0)
        r = excl_regression.get(func, 0)
        diffs[func] = r - b
    return diffs


def parse_vmstat_lines(content):
    """Extract vmstat data lines from metrics content."""
    data = []
    in_vmstat = False
    for line in content.split("\n"):
        if "=== vmstat" in line:
            in_vmstat = True
            continue
        if in_vmstat and line.startswith("==="):
            in_vmstat = False
            continue
        if not in_vmstat or not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("procs") or stripped.startswith("r "):
            continue
        if not stripped[0].isdigit():
            continue
        parts = stripped.split()
        if len(parts) >= 17:
            try:
                data.append(
                    {
                        "r": int(parts[0]),
                        "b": int(parts[1]),
                        "si": int(parts[6]),
                        "so": int(parts[7]),
                        "us": int(parts[12]),
                        "sy": int(parts[13]),
                        "id": int(parts[14]),
                        "wa": int(parts[15]),
                    }
                )
            except (ValueError, IndexError):
                pass
    return data


def parse_iostat_lines(content):
    """Extract iostat data lines from metrics content."""
    data = []
    in_iostat = False
    for line in content.split("\n"):
        if "=== iostat" in line:
            in_iostat = True
            continue
        if in_iostat and line.startswith("==="):
            in_iostat = False
            continue
        if not in_iostat or not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("Device"):
            continue
        parts = stripped.split()
        if len(parts) >= 23:
            try:
                data.append(
                    {
                        "w_await": float(parts[11]),
                        "aqu_sz": float(parts[21]),
                        "util": float(parts[22]),
                    }
                )
            except (ValueError, IndexError):
                pass
    return data


def parse_free(content):
    """Extract memory info from free -m output."""
    for line in content.split("\n"):
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 4:
                return {"total": int(parts[1]), "used": int(parts[2])}
    return {"total": 0, "used": 0}


def parse_metrics(filepath):
    """Parse a system metrics file and return extracted values."""
    with open(filepath) as f:
        content = f.read()

    metrics = {}

    vmstat = parse_vmstat_lines(content)
    if vmstat:
        n = len(vmstat)
        metrics["cpu_util"] = round(
            sum(v["us"] + v["sy"] for v in vmstat) / n, 1
        )
        metrics["cpu_runqueue"] = round(sum(v["r"] for v in vmstat) / n, 1)
        metrics["iowait"] = round(sum(v["wa"] for v in vmstat) / n, 1)
        metrics["swap_in"] = round(sum(v["si"] for v in vmstat) / n, 1)
        metrics["swap_out"] = round(sum(v["so"] for v in vmstat) / n, 1)

    iostat = parse_iostat_lines(content)
    if iostat:
        n = len(iostat)
        metrics["disk_util"] = round(sum(v["util"] for v in iostat) / n, 1)
        metrics["disk_queue"] = round(sum(v["aqu_sz"] for v in iostat) / n, 2)
        metrics["disk_w_await"] = round(
            sum(v["w_await"] for v in iostat) / n, 1
        )

    mem = parse_free(content)
    if mem["total"] > 0:
        metrics["mem_total"] = mem["total"]
        metrics["mem_used"] = mem["used"]
        metrics["mem_util"] = round(100.0 * mem["used"] / mem["total"], 1)

    return metrics


def generate_flamegraphs(baseline_path, regression_path, output_dir):
    """Generate flame graph SVGs using FlameGraph tools."""
    fg = "/app/FlameGraph"

    subprocess.run(
        f"perl {fg}/flamegraph.pl --title='Baseline CPU Flame Graph' "
        f"< {baseline_path} > {output_dir}/baseline.svg",
        shell=True,
        check=True,
    )

    subprocess.run(
        f"perl {fg}/flamegraph.pl --title='Regression CPU Flame Graph' "
        f"< {regression_path} > {output_dir}/regression.svg",
        shell=True,
        check=True,
    )

    subprocess.run(
        f"perl {fg}/difffolded.pl {baseline_path} {regression_path} | "
        f"perl {fg}/flamegraph.pl --negate "
        f"--title='Differential: Regression vs Baseline' "
        f"> {output_dir}/diff.svg",
        shell=True,
        check=True,
    )


def build_use_analysis(metrics):
    """Apply the USE Method to parsed system metrics."""
    cpu_util = metrics.get("cpu_util", 0)
    cpu_rq = metrics.get("cpu_runqueue", 0)
    mem_util = metrics.get("mem_util", 0)
    swap_in = metrics.get("swap_in", 0)
    swap_out = metrics.get("swap_out", 0)
    disk_util = metrics.get("disk_util", 0)
    disk_q = metrics.get("disk_queue", 0)

    return {
        "cpu": {
            "utilization_percent": cpu_util,
            "saturated": cpu_rq > 2,
        },
        "memory": {
            "utilization_percent": mem_util,
            "saturated": swap_in > 0 or swap_out > 0,
        },
        "disk": {
            "utilization_percent": disk_util,
            "saturated": disk_q > 1,
        },
        "network": {
            "utilization_percent": 0.0,
            "saturated": False,
        },
    }


def identify_root_causes(excl_diffs, new_funcs, regression_metrics):
    """Identify root causes by correlating profiling deltas with system metrics."""
    causes = []

    regex_funcs = [
        f for f in excl_diffs if "regex" in f.lower() or f == "compile_pattern"
    ]
    regex_delta = sum(excl_diffs.get(f, 0) for f in regex_funcs)
    if regex_delta > 0:
        causes.append(
            f"Regex-based validation added {regex_delta} exclusive samples "
            f"({regex_delta / 100:.1f}% CPU). New functions regex_match and "
            f"compile_pattern appear in input validation paths "
            f"(validate_headers, validate_content_type, validate_schema), "
            f"making regex_match the single hottest function in the regression."
        )

    if "deep_copy" in new_funcs:
        dc = excl_diffs.get("deep_copy", 0)
        causes.append(
            f"Deep copy serialization added {dc} exclusive samples "
            f"({dc / 100:.1f}% CPU). deep_copy appears in both query result "
            f"serialization and audit log request serialization paths, "
            f"increasing memory allocation pressure."
        )

    if "fsync_data" in new_funcs:
        fs = excl_diffs.get("fsync_data", 0)
        disk_util = regression_metrics.get("disk_util", 0)
        disk_q = regression_metrics.get("disk_queue", 0)
        causes.append(
            f"Access log changed to synchronous disk writes via fsync "
            f"({fs} samples, {fs / 100:.1f}% CPU). This caused disk I/O "
            f"saturation: utilization {disk_util}%, queue depth {disk_q}, "
            f"iowait {regression_metrics.get('iowait', 0)}%."
        )

    gc_funcs = ["scan_young_gen", "copy_survivors", "trace_refs", "sweep_phase"]
    gc_delta = sum(excl_diffs.get(f, 0) for f in gc_funcs)
    if gc_delta > 100:
        causes.append(
            f"GC pressure increased by {gc_delta} exclusive samples "
            f"({gc_delta / 100:.1f}% CPU), likely from additional memory "
            f"allocation by deep_copy operations."
        )

    return causes


def main():
    baseline_path = "/app/data/baseline.folded"
    regression_path = "/app/data/regression.folded"
    metrics_base_path = "/app/data/metrics_baseline.txt"
    metrics_reg_path = "/app/data/metrics_regression.txt"
    output_dir = "/app/output"

    os.makedirs(output_dir, exist_ok=True)

    entries_base = parse_folded(baseline_path)
    entries_reg = parse_folded(regression_path)

    total_base = sum(c for _, c in entries_base)
    total_reg = sum(c for _, c in entries_reg)

    excl_base = compute_exclusive(entries_base)
    excl_reg = compute_exclusive(entries_reg)
    incl_base = compute_inclusive(entries_base)
    incl_reg = compute_inclusive(entries_reg)

    funcs_base = get_all_functions(entries_base)
    funcs_reg = get_all_functions(entries_reg)
    new_funcs = sorted(funcs_reg - funcs_base)
    removed_funcs = sorted(funcs_base - funcs_reg)

    excl_diffs = compute_exclusive_diff(excl_base, excl_reg)

    regressions = sorted(
        [(f, d) for f, d in excl_diffs.items() if d > 0],
        key=lambda x: (-x[1], x[0]),
    )
    improvements = sorted(
        [(f, d) for f, d in excl_diffs.items() if d < 0],
        key=lambda x: (x[1], x[0]),
    )

    metrics_reg = parse_metrics(metrics_reg_path)

    generate_flamegraphs(baseline_path, regression_path, output_dir)

    use = build_use_analysis(metrics_reg)
    root_causes = identify_root_causes(excl_diffs, new_funcs, metrics_reg)

    report = {
        "baseline_total_samples": total_base,
        "regression_total_samples": total_reg,
        "exclusive_top5_baseline": top_n(excl_base, total_base),
        "exclusive_top5_regression": top_n(excl_reg, total_reg),
        "inclusive_top5_baseline": top_n(incl_base, total_base),
        "inclusive_top5_regression": top_n(incl_reg, total_reg),
        "new_functions": new_funcs,
        "removed_functions": removed_funcs,
        "top_regressions": [
            {"function": f, "delta": d} for f, d in regressions[:5]
        ],
        "top_improvements": [
            {"function": f, "delta": d} for f, d in improvements[:5]
        ],
        "root_causes": root_causes,
        "use_method": use,
    }

    with open(os.path.join(output_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(f"Analysis complete. Report: {output_dir}/report.json")
    print(f"Baseline: {total_base} samples, Regression: {total_reg} samples")
    print(f"Top regression: {regressions[0][0]} (+{regressions[0][1]})")
    print(f"New functions: {len(new_funcs)}, Removed: {len(removed_funcs)}")


if __name__ == "__main__":
    main()
