#!/usr/bin/env python3
"""Magma fuzzing campaign results analysis pipeline.

Parses the Magma captain workdir hierarchy, extracts time-to-reach and
time-to-trigger for each bug, produces exp2json-compatible results,
pairwise statistical comparisons (A12 + Mann-Whitney U), and a
human-readable report.
"""

import json
import os
from collections import defaultdict
from itertools import combinations

import numpy as np
from scipy import stats


def read_captainrc(workdir):
    """Parse captainrc for POLL and TIMEOUT."""
    path = os.path.join(workdir, "captainrc")
    poll = 5
    timeout = 300

    if not os.path.exists(path):
        return poll, timeout

    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("POLL="):
                poll = int(line.split("=", 1)[1])
            elif line.startswith("TIMEOUT="):
                val = line.split("=", 1)[1]
                if val.endswith("s"):
                    timeout = int(val[:-1])
                elif val.endswith("m"):
                    timeout = int(val[:-1]) * 60
                elif val.endswith("h"):
                    timeout = int(val[:-1]) * 3600
                elif val.endswith("d"):
                    timeout = int(val[:-1]) * 86400
                else:
                    timeout = int(val)

    return poll, timeout


def discover_campaigns(workdir):
    """Walk the ar/ directory to find all campaign directories."""
    ar_dir = os.path.join(workdir, "ar")
    campaigns = []

    if not os.path.isdir(ar_dir):
        return campaigns

    for fuzzer in sorted(os.listdir(ar_dir)):
        fuzzer_path = os.path.join(ar_dir, fuzzer)
        if not os.path.isdir(fuzzer_path):
            continue

        for target in sorted(os.listdir(fuzzer_path)):
            target_path = os.path.join(fuzzer_path, target)
            if not os.path.isdir(target_path):
                continue

            for program in sorted(os.listdir(target_path)):
                program_path = os.path.join(target_path, program)
                if not os.path.isdir(program_path):
                    continue

                for run_id in sorted(os.listdir(program_path), key=lambda x: int(x) if x.isdigit() else x):
                    run_path = os.path.join(program_path, run_id)
                    if not os.path.isdir(run_path):
                        continue

                    campaigns.append({
                        "fuzzer": fuzzer,
                        "target": target,
                        "program": program,
                        "run_id": run_id,
                        "path": run_path,
                    })

    return campaigns


def parse_monitor_csv(csv_path, poll):
    """Parse a Magma monitor CSV and return (reached, triggered, status).

    reached/triggered: dict mapping bug_id to first-event time in seconds.
    status: "ok", "empty", or an error string.
    """
    reached = {}
    triggered = {}

    try:
        with open(csv_path) as f:
            content = f.read().strip()
    except Exception as e:
        return reached, triggered, f"read_error: {e}"

    if not content:
        return reached, triggered, "empty"

    lines = content.split("\n")
    if len(lines) < 2:
        return reached, triggered, "header_only"

    # Parse header
    headers = [h.strip() for h in lines[0].split(",")]

    # Parse data rows
    for row_idx, line in enumerate(lines[1:]):
        time_sec = (row_idx + 1) * poll
        values = [v.strip() for v in line.split(",")]

        for col_idx, header in enumerate(headers):
            if col_idx >= len(values):
                continue

            try:
                val = int(values[col_idx])
            except ValueError:
                continue

            if header.endswith("_R"):
                bug_id = header[:-2]
                if bug_id not in reached and val > 0:
                    reached[bug_id] = time_sec

            elif header.endswith("_T"):
                bug_id = header[:-2]
                if bug_id not in triggered and val > 0:
                    triggered[bug_id] = time_sec

    return reached, triggered, "ok"


def compute_a12(x, y):
    """Vargha-Delaney A12 measure: P(X > Y) + 0.5 * P(X == Y)."""
    m, n = len(x), len(y)
    if m == 0 or n == 0:
        return 0.5

    count = 0.0
    for xi in x:
        for yj in y:
            if xi > yj:
                count += 1.0
            elif xi == yj:
                count += 0.5

    return count / (m * n)


def classify_a12(a12):
    """Classify A12 magnitude using Vargha-Delaney thresholds."""
    if 0.44 <= a12 <= 0.56:
        return "negligible"
    elif (0.56 < a12 <= 0.64) or (0.36 <= a12 < 0.44):
        return "small"
    elif (0.64 < a12 <= 0.71) or (0.29 <= a12 < 0.36):
        return "medium"
    else:
        return "large"


def build_results(campaigns, poll):
    """Build exp2json-format results dict."""
    results = {}
    issues = []

    for campaign in campaigns:
        fuzzer = campaign["fuzzer"]
        target = campaign["target"]
        program = campaign["program"]
        run_id = campaign["run_id"]

        csv_path = os.path.join(campaign["path"], "monitor.csv")
        if not os.path.exists(csv_path):
            issues.append(f"Missing monitor.csv: {campaign['path']}")
            continue

        reached, triggered, status = parse_monitor_csv(csv_path, poll)

        if status in ("empty", "header_only"):
            issues.append(f"Empty/unreadable CSV: {csv_path}")
            continue

        if status.startswith("read_error"):
            issues.append(f"Read error: {csv_path} — {status}")
            continue

        # Insert into nested dict
        results.setdefault(fuzzer, {})
        results[fuzzer].setdefault(target, {})
        results[fuzzer][target].setdefault(program, {})
        results[fuzzer][target][program][run_id] = {
            "reached": reached,
            "triggered": triggered,
        }

    return results, issues


def build_statistics(results, timeout):
    """Compute pairwise A12 / Mann-Whitney U and per-fuzzer coverage."""
    statistics = {"pairwise": {}, "coverage": {}}

    fuzzers = sorted(results.keys())

    # Discover all bugs per (target, program)
    target_bugs = defaultdict(set)
    for fuzzer in fuzzers:
        for target in results[fuzzer]:
            for program in results[fuzzer][target]:
                for run_id, run_data in results[fuzzer][target][program].items():
                    target_bugs[(target, program)].update(run_data["reached"].keys())
                    target_bugs[(target, program)].update(run_data["triggered"].keys())

    # Coverage per fuzzer
    for fuzzer in fuzzers:
        all_reached = set()
        all_triggered = set()
        for target in results.get(fuzzer, {}):
            for program in results[fuzzer][target]:
                for run_id, run_data in results[fuzzer][target][program].items():
                    all_reached.update(run_data["reached"].keys())
                    all_triggered.update(run_data["triggered"].keys())

        statistics["coverage"][fuzzer] = {
            "unique_reached": sorted(list(all_reached)),
            "unique_triggered": sorted(list(all_triggered)),
        }

    # Pairwise comparisons
    for f1, f2 in combinations(fuzzers, 2):
        pair_key = f"{f1}_vs_{f2}"
        statistics["pairwise"][pair_key] = {}

        for (target, program), bugs in sorted(target_bugs.items()):
            # Both fuzzers must have data for this target/program
            if target not in results.get(f1, {}) or target not in results.get(f2, {}):
                continue
            if program not in results[f1].get(target, {}) or program not in results[f2].get(target, {}):
                continue

            tp_key = f"{target}/{program}"
            statistics["pairwise"][pair_key][tp_key] = {}

            for bug in sorted(bugs):
                # Collect trigger times (timeout for untriggered)
                times1 = []
                for run_id in sorted(results[f1][target][program].keys()):
                    t = results[f1][target][program][run_id]["triggered"].get(bug, timeout)
                    times1.append(t)

                times2 = []
                for run_id in sorted(results[f2][target][program].keys()):
                    t = results[f2][target][program][run_id]["triggered"].get(bug, timeout)
                    times2.append(t)

                if not times1 or not times2:
                    continue

                a12 = compute_a12(times1, times2)
                magnitude = classify_a12(a12)

                # Mann-Whitney U test
                try:
                    if len(set(times1 + times2)) == 1:
                        p_value = 1.0
                    else:
                        _, p_value = stats.mannwhitneyu(
                            times1, times2, alternative="two-sided"
                        )
                except Exception:
                    p_value = None

                statistics["pairwise"][pair_key][tp_key][bug] = {
                    "a12": round(a12, 4),
                    "a12_magnitude": magnitude,
                    "p_value": round(p_value, 4) if p_value is not None else None,
                }

    return statistics


def build_report(results, statistics, issues, timeout):
    """Generate a human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("MAGMA FUZZING CAMPAIGN ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Count campaigns
    total = 0
    for fuzzer in results:
        for target in results[fuzzer]:
            for program in results[fuzzer][target]:
                total += len(results[fuzzer][target][program])
    lines.append(f"Total campaigns analyzed: {total}")
    lines.append(f"Fuzzers: {', '.join(sorted(results.keys()))}")
    lines.append("")

    # Data quality issues
    if issues:
        lines.append("Data Quality Issues:")
        for issue in issues:
            lines.append(f"  - {issue}")
        lines.append("")

    # Coverage summary
    lines.append("Bug Coverage Summary:")
    lines.append("-" * 40)
    for fuzzer in sorted(results.keys()):
        cov = statistics["coverage"][fuzzer]
        lines.append(f"  {fuzzer}:")
        lines.append(f"    Bugs reached:   {len(cov['unique_reached'])} "
                      f"({', '.join(cov['unique_reached'])})")
        lines.append(f"    Bugs triggered: {len(cov['unique_triggered'])} "
                      f"({', '.join(cov['unique_triggered'])})")
    lines.append("")

    # Best fuzzer per bug
    fuzzers = sorted(results.keys())
    target_bugs = defaultdict(set)
    for fuzzer in fuzzers:
        for target in results[fuzzer]:
            for program in results[fuzzer][target]:
                for run_id, run_data in results[fuzzer][target][program].items():
                    target_bugs[(target, program)].update(run_data["reached"].keys())
                    target_bugs[(target, program)].update(run_data["triggered"].keys())

    lines.append("Best Fuzzer per Bug (by median time-to-trigger):")
    lines.append("-" * 40)
    for (target, program), bugs in sorted(target_bugs.items()):
        lines.append(f"  {target}/{program}:")
        for bug in sorted(bugs):
            median_times = {}
            for fuzzer in fuzzers:
                if (target in results.get(fuzzer, {})
                        and program in results[fuzzer].get(target, {})):
                    times = []
                    for run_id in results[fuzzer][target][program]:
                        t = results[fuzzer][target][program][run_id]["triggered"].get(
                            bug, timeout
                        )
                        times.append(t)
                    median_times[fuzzer] = float(np.median(times))

            if median_times:
                best = min(median_times, key=median_times.get)
                best_time = median_times[best]
                if best_time >= timeout:
                    lines.append(f"    {bug}: No fuzzer triggered this bug")
                else:
                    lines.append(f"    {bug}: {best} (median {best_time:.0f}s)")
    lines.append("")

    # Pairwise summary
    lines.append("Pairwise Comparison Summary (A12 > 0.5 → second fuzzer better):")
    lines.append("-" * 40)
    for pair_key in sorted(statistics["pairwise"].keys()):
        lines.append(f"  {pair_key}:")
        for tp_key in sorted(statistics["pairwise"][pair_key].keys()):
            lines.append(f"    {tp_key}:")
            for bug in sorted(statistics["pairwise"][pair_key][tp_key].keys()):
                entry = statistics["pairwise"][pair_key][tp_key][bug]
                a12 = entry["a12"]
                mag = entry["a12_magnitude"]
                p_val = entry["p_value"]
                sig = " *" if p_val is not None and p_val < 0.05 else ""
                lines.append(
                    f"      {bug}: A12={a12:.4f} ({mag}) p={p_val}{sig}"
                )

    return "\n".join(lines) + "\n"


def main():
    workdir = "/app/workdir"

    poll, timeout = read_captainrc(workdir)
    print(f"Configuration: POLL={poll}s, TIMEOUT={timeout}s")

    campaigns = discover_campaigns(workdir)
    print(f"Discovered {len(campaigns)} campaign directories")

    results, issues = build_results(campaigns, poll)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
    print("Wrote /app/results.json")

    statistics = build_statistics(results, timeout)

    with open("/app/statistics.json", "w") as f:
        json.dump(statistics, f, indent=2, sort_keys=True)
    print("Wrote /app/statistics.json")

    report = build_report(results, statistics, issues, timeout)

    with open("/app/report.txt", "w") as f:
        f.write(report)
    print("Wrote /app/report.txt")

    if issues:
        print(f"Data quality issues found: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")

    print("Analysis complete.")


if __name__ == "__main__":
    main()
