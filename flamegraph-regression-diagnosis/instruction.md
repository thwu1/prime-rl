A C record-processing service at `/app/workload.c` has degraded in production. Two folded stack trace profiles captured with `perf` are provided:

- `/app/profile_before.folded` — baseline (pre-degradation)
- `/app/profile_after.folded` — current (degraded)

FlameGraph tools are at `/app/FlameGraph/`. The program reads tab-separated records, validates fields, normalizes text, looks up records in a hash-indexed file, and writes processed output. Several functions were recently added or modified across security, monitoring, and processing codepaths.

The degraded profile contains multiple functions with anomalous sample count changes compared to baseline. Not all anomalies are genuine performance bugs — some reflect intentional code additions (security hardening, observability instrumentation) or expected workload-proportional scaling. Incorrectly "fixing" a non-bug would remove security protections or break production monitoring. Your task is to perform expert-level triage, separating genuine regressions from false positives, then remediate only the real issues.

Deliver:

**`/app/triage.json`** — JSON with a `triage` array. For every function exhibiting anomalous sample behavior, include: `function` (name), `classification` (`genuine_regression`, `intentional_addition`, or `expected_overhead`), and `justification` (evidence-based explanation referencing sample counts, algorithmic analysis, and code purpose).

**`/app/workload.c`** — Fix only genuine regressions. Do not remove or alter functions classified as intentional additions or expected overhead. The fixed program must compile with `gcc -O2`, produce byte-identical output to `/app/reference_output.txt` when run as `./workload /app/test_data.txt /app/index_data.txt /tmp/output.txt`, and process 2000 records with a 500-entry index in under 10 seconds.

**`/app/impact_analysis.json`** — JSON with an `analysis` array, one entry per genuine regression. Each entry: `function`, `before_samples`, `after_samples`, `regression_delta`, `total_after_samples`, `fraction_of_profile` (regression delta as fraction of total after-profile samples), and `amdahl_projected_speedup` (Amdahl's law projected speedup from eliminating that regression).

**`/app/perf_guardian.py`** — Automated regression detection tool. Accepts two folded profile paths as positional arguments and optional `--threshold` (minimum absolute sample delta to report, default 500). Writes JSON to stdout with a `regressions` array; each entry: `function`, `before_samples`, `after_samples`, `delta`, `percent_change`, `severity` (`critical`/`warning`/`info`). Must detect the genuine regressions when run on the provided profiles.

Config: `/app/config.ini`. Test command: `./workload /app/test_data.txt /app/index_data.txt /tmp/output.txt`