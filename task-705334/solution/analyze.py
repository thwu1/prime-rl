#!/usr/bin/env python3
"""
Differential flame graph root cause analyzer.

Parses time-series folded stack profiles, builds call-graph models,
separates root-cause regressions from propagated effects, computes
correlations with system metrics, and produces a structured diagnosis.

"""

import csv
import json
import math
import os
from collections import defaultdict


def parse_folded(path):
    stacks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            frames = parts[0].split(";")
            count = int(parts[1])
            stacks.append((frames, count))
    return stacks


def total_samples(stacks):
    return sum(c for _, c in stacks)


def compute_self_counts(stacks):
    self_counts = defaultdict(int)
    for frames, count in stacks:
        self_counts[frames[-1]] += count
    return dict(self_counts)


def compute_inclusive_counts(stacks):
    inclusive = defaultdict(int)
    for frames, count in stacks:
        seen = set()
        for func in frames:
            if func not in seen:
                inclusive[func] += count
                seen.add(func)
    return dict(inclusive)


def get_all_functions(stacks):
    funcs = set()
    for frames, _ in stacks:
        funcs.update(frames)
    return funcs


def get_ancestors_of(stacks, func_name):
    ancestors = set()
    for frames, _ in stacks:
        for i, func in enumerate(frames):
            if func == func_name:
                for j in range(i):
                    ancestors.add(frames[j])
                break
    return ancestors


def get_descendants_of(stacks, func_name):
    descendants = set()
    for frames, _ in stacks:
        found = False
        for func in frames:
            if found:
                descendants.add(func)
            if func == func_name:
                found = True
    return descendants


def pearson_correlation(x, y):
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


def classify_regression(stacks, func_name):
    for frames, _ in stacks:
        for i, func in enumerate(frames):
            if func == func_name:
                context = frames[max(0, i - 2):i + 3]
                context_str = ";".join(context).lower()
                if any(k in context_str for k in ["spin_lock", "mutex", "lock", "acquire"]):
                    return "lock_contention"
                if any(k in context_str for k in ["mmap", "alloc", "brk", "malloc"]):
                    return "memory_allocation"
                if any(k in context_str for k in ["read", "write", "io", "sync", "flush"]):
                    return "io_blocking"
                return "cpu_compute"
    return "cpu_compute"


def main():
    windows = ["t0", "t1", "t2", "t3", "t4"]
    profiles = {}
    for w in windows:
        profiles[w] = parse_folded(f"/app/profiles/{w}.folded")

    totals = {w: total_samples(s) for w, s in profiles.items()}
    self_counts = {w: compute_self_counts(s) for w, s in profiles.items()}
    inclusive_counts = {w: compute_inclusive_counts(s) for w, s in profiles.items()}
    all_funcs = {w: get_all_functions(s) for w, s in profiles.items()}

    # Identify root cause: function with largest self-time delta t0->t4
    t0_self = self_counts["t0"]
    t4_self = self_counts["t4"]
    every_func = set()
    for funcs in all_funcs.values():
        every_func |= funcs

    self_deltas = {}
    for func in every_func:
        delta = t4_self.get(func, 0) - t0_self.get(func, 0)
        if delta > 0:
            self_deltas[func] = delta

    root_cause = max(self_deltas, key=self_deltas.get)

    # Classification
    regression_category = classify_regression(profiles["t4"], root_cause)

    # Inclusive and self fraction series
    inclusive_frac_series = []
    self_frac_series = []
    for w in windows:
        incl = inclusive_counts[w].get(root_cause, 0)
        self_ = self_counts[w].get(root_cause, 0)
        total = totals[w]
        inclusive_frac_series.append(round(incl / total, 4))
        self_frac_series.append(round(self_ / total, 4))

    # Onset window
    baseline_frac = inclusive_frac_series[0]
    onset_window = None
    for i in range(1, 5):
        if baseline_frac == 0:
            if inclusive_frac_series[i] > 0:
                onset_window = i
                break
        elif inclusive_frac_series[i] > 3 * baseline_frac:
            onset_window = i
            break

    # Cascading functions: new + descendant of root cause
    t0_funcs = all_funcs["t0"]
    new_funcs = set()
    for w in windows[1:]:
        new_funcs |= (all_funcs[w] - t0_funcs)

    all_descendants = set()
    for w in windows:
        all_descendants |= get_descendants_of(profiles[w], root_cause)

    cascading = sorted(new_funcs & all_descendants)

    # Growth classification: classify every function new since t0
    growth_classification = {}
    for func in sorted(new_funcs):
        if func == root_cause:
            growth_classification[func] = "root_cause"
        elif func in all_descendants:
            growth_classification[func] = "causal_descendant"
        else:
            growth_classification[func] = "independent"

    # Propagation ancestors
    all_ancestors = set()
    for w in windows:
        all_ancestors |= get_ancestors_of(profiles[w], root_cause)
    all_ancestors.discard("main")
    propagation_ancestors = sorted(all_ancestors)

    # Subsystem regression share
    delta_total = totals["t4"] - totals["t0"]
    subsystem_t0 = defaultdict(int)
    for frames, count in profiles["t0"]:
        if len(frames) >= 2:
            subsystem_t0[frames[1]] += count
    subsystem_t4 = defaultdict(int)
    for frames, count in profiles["t4"]:
        if len(frames) >= 2:
            subsystem_t4[frames[1]] += count

    all_subsystems = set(subsystem_t0.keys()) | set(subsystem_t4.keys())
    subsystem_share = {}
    for sub in sorted(all_subsystems):
        delta = subsystem_t4.get(sub, 0) - subsystem_t0.get(sub, 0)
        subsystem_share[sub] = round(delta / delta_total, 4)

    # Read metrics and compute Pearson correlation
    ctx_switches = []
    with open("/app/metrics.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ctx_switches.append(float(row["ctx_switches_per_sec"]))

    pearson = round(pearson_correlation(inclusive_frac_series, ctx_switches), 4)

    # Check SVG was generated
    svg_path = "/app/output/diff_t0_t4.svg"
    svg_exists = os.path.isfile(svg_path)

    results = {
        "root_cause": root_cause,
        "regression_category": regression_category,
        "onset_window": onset_window,
        "inclusive_fraction_series": inclusive_frac_series,
        "self_fraction_series": self_frac_series,
        "cascading_functions": cascading,
        "growth_classification": growth_classification,
        "propagation_ancestors": propagation_ancestors,
        "subsystem_regression_share": subsystem_share,
        "pearson_ctx_switches": pearson,
        "diff_svg_path": svg_path if svg_exists else "",
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
