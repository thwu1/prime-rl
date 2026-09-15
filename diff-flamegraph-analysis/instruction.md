A production `appserver` process experienced a 3x p99 latency regression after deploying v2.5.0. Raw performance traces from before and during the incident are at `/app/traces/`. The Brendan Gregg FlameGraph toolchain is installed at `/opt/FlameGraph/`.

## Available Data

- `/app/traces/baseline.perf` — Raw `perf script` output, **system-wide** capture during baseline (contains multiple processes)
- `/app/traces/incident.perf` — Raw `perf script` output, system-wide capture during incident
- `/app/traces/offcpu_stacks.txt` — Off-CPU stack traces for the target process during the incident (bpftrace `@usecs` map format, leaf-first ordering)
- `/app/traces/sysmetrics.csv` — Scheduler latency, CPU utilization, and I/O wait metrics spanning both windows
- `/app/traces/manifest.json` — Collection parameters (process name, PIDs, durations, timestamps)

The baseline and incident captures have **different durations**. The perf data captures **all processes** on the host; only the target process is relevant.

## Required Artifacts

Produce all files in `/app/output/`:

| File | Description |
|------|-------------|
| `baseline.folded` | Collapsed baseline stacks, target process only, folded format |
| `incident.folded` | Collapsed incident stacks, target process only, folded format |
| `diff.folded` | Differential folded output (baseline vs incident) |
| `diff_flamegraph.svg` | Differential flame graph |
| `offcpu.folded` | Off-CPU stacks converted to folded format |
| `offcpu_flamegraph.svg` | Off-CPU flame graph |
| `triage.json` | Structured root-cause triage report |

## Triage Report Schema (`/app/output/triage.json`)

```json
{
  "summary": {
    "baseline_oncpu_samples": "<int>",
    "incident_oncpu_samples": "<int>",
    "duration_ratio": "<float>",
    "root_cause_class": "<cpu_regression | io_regression | lock_contention | mixed>"
  },
  "oncpu_regressions": [
    {"function": "<str>", "baseline_pct": "<float>", "incident_pct": "<float>", "delta_pct": "<float>"}
  ],
  "oncpu_improvements": [
    {"function": "<str>", "baseline_pct": "<float>", "incident_pct": "<float>", "delta_pct": "<float>"}
  ],
  "offcpu_hotspots": [
    {"function": "<str>", "total_us": "<int>", "category": "<io | lock | network | idle>"}
  ],
  "elided_code_paths": ["<semicolon-delimited stack paths present only in baseline>"],
  "new_code_paths": ["<semicolon-delimited stack paths present only in incident>"],
  "diagnosis": "<free-text root-cause explanation>"
}
```

`oncpu_regressions` / `oncpu_improvements`: Leaf (self/exclusive) functions sorted by `|delta_pct|` descending. `delta_pct` = incident exclusive% minus baseline exclusive%. Include only functions where `|delta_pct| > 0.5`.

`offcpu_hotspots`: Non-idle off-CPU stacks categorized by blocking reason, sorted by duration descending. The representative function is the last application-level frame before the kernel/libc boundary. Exclude voluntary waits (epoll, sleep).

`root_cause_class`: Cross-correlate on-CPU regressions with off-CPU blocking patterns and system metrics to determine whether the regression is CPU-bound, I/O-bound, lock-contention, or a combination.