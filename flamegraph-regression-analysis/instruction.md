A production web service experienced a performance regression after a code deployment. Two CPU profiling snapshots were collected as folded stack trace files (Brendan Gregg's FlameGraph format: semicolon-delimited stack frames followed by a sample count), along with system metric snapshots (vmstat, iostat, mpstat, free) captured during each profiling window.

Data files:
- `/app/data/baseline.folded` — CPU profile before deployment
- `/app/data/regression.folded` — CPU profile after deployment
- `/app/data/metrics_baseline.txt` — System metrics before deployment
- `/app/data/metrics_regression.txt` — System metrics after deployment

FlameGraph tools (flamegraph.pl, difffolded.pl, etc.) are at `/app/FlameGraph/`.

Create `/app/analyze.py` that produces these outputs in `/app/output/`:

- `baseline.svg` — Flame graph from baseline data
- `regression.svg` — Flame graph from regression data
- `diff.svg` — Differential flame graph (regression vs baseline)
- `report.json` — Structured analysis report

The `report.json` must contain exactly these top-level fields:

- `baseline_total_samples` (int): Total sample count from baseline
- `regression_total_samples` (int): Total sample count from regression
- `exclusive_top5_baseline` (list): Top 5 functions by exclusive sample count from baseline, each entry `{"function": str, "samples": int, "percent": float}`, sorted descending by samples (ties broken alphabetically)
- `exclusive_top5_regression` (list): Same structure for regression
- `inclusive_top5_baseline` (list): Top 5 functions by inclusive sample count from baseline, same entry structure
- `inclusive_top5_regression` (list): Same structure for regression
- `new_functions` (list of str): Function names appearing anywhere in regression stacks but not in baseline stacks
- `removed_functions` (list of str): Function names appearing anywhere in baseline stacks but not in regression stacks
- `top_regressions` (list): Top 5 functions with largest positive exclusive sample delta (regression minus baseline), each `{"function": str, "delta": int}`, sorted descending by delta
- `top_improvements` (list): Top 5 functions with largest magnitude negative exclusive sample delta, each `{"function": str, "delta": int}` (delta is negative), sorted ascending by delta
- `root_causes` (list of str): Identified performance regression root causes with explanations
- `use_method` (object): USE Method analysis of the regression system metrics. Keys: `cpu`, `memory`, `disk`, `network`. Each contains `utilization_percent` (float) and `saturated` (bool)

Definitions: "Exclusive" (self) count = samples where the function is the leaf (rightmost) frame. "Inclusive" (cumulative) count = samples from all stacks where the function appears at any depth. When a function name appears in multiple distinct stacks, sum across all occurrences. Percentages = 100 * samples / total_samples. USE Method: utilization = time resource was busy (%), saturated = resource has queued work beyond capacity.