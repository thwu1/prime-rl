# CORAL-2 Procurement Evaluation Protocol v2.1

## 1. Objective

This protocol defines the methodology for independent validation of benchmark
results submitted by candidate HPC systems as part of the CORAL-2 procurement
evaluation. The evaluator must verify data integrity, validate reported figures
of merit against raw measurements, assess physical plausibility of results, and
produce a defensible procurement ranking.

## 2. Data Sources

| Document | Path | Purpose |
|----------|------|---------|
| Benchmark database | `/app/benchmark.db` | Raw run data, measurements, configurations |
| Benchmark specs | `/app/docs/benchmark_specs.md` | Authoritative FOM formulas |
| Machine-readable spec | `/app/docs/benchmark_spec.toml` | Supplementary (may contain errors) |
| Standard configs | `/app/docs/standard_configs.toml` | Reference configurations |
| Scoring config | `/app/config.toml` | Weights, thresholds, parameters |

## 3. Validation Dimensions

### 3.1 Run-Level Data Integrity

Identify and exclude runs with:
- Non-passing execution status
- Missing or null values for any measurement field required by the FOM formula
- Temporal anomalies: consecutive runs on the same system-benchmark pair whose
  timestamps are separated by less than `min_run_interval_seconds` (see config)

When detecting temporal anomalies, sort valid (non-error) runs by timestamp
within each system-benchmark group. If any pair of adjacent runs has a gap
below the threshold, mark both runs as anomalous.

Document each exclusion with the run identifier and reason.

### 3.2 FOM Recomputation and Discrepancy Detection

Independently compute each run's Figure of Merit from raw measurement data
using the authoritative formulas in the benchmark specification. Compare the
independently computed value against the `reported_fom` stored in the database.

Any divergence exceeding 1% constitutes a reportable discrepancy. Compute the
signed percentage error as:

    pct_error = (reported_fom - computed_fom) / computed_fom * 100

Systematic discrepancy patterns (e.g., all runs of a particular benchmark
showing similar error magnitudes) indicate calculation bugs in the submission
pipeline rather than random measurement noise.

### 3.3 Configuration Compliance

Cross-reference each valid run's configuration parameters against the standard
reference configuration. Non-standard configurations compromise cross-system
comparability. Flag system-benchmark pairs where any run deviates from the
standard. Check at minimum: AMG grid dimensions, Kripke zone/direction/group
counts, STREAM array size, PENNANT mesh type and scale.

### 3.4 Statistical Quality

For each system-benchmark pair with valid runs, assess:
- Whether the number of distinct FOM values (rounded to 2 decimal places)
  meets the `min_distinct_fom_values` threshold — insufficient variance
  suggests measurement clamping or fabrication
- Whether timing anomalies are present at the system-benchmark level
  (indicating batch-submitted rather than independently executed runs)

### 3.5 Physical Plausibility and Cross-Benchmark Consistency

#### Memory Bandwidth Efficiency

For each system, compute memory bandwidth efficiency from STREAM results:

    efficiency = median_measured_triad_bandwidth / theoretical_peak_bandwidth

where `theoretical_peak_bandwidth` is recorded in the STREAM measurement data
in the database. No system may achieve efficiency > 1.0 (a physical
impossibility indicating measurement or specification error). Well-configured
systems typically achieve 75-90% efficiency.

#### Cross-Benchmark Consistency

AMG is a memory-bandwidth-sensitive benchmark. Its throughput FOM should
correlate with measured memory bandwidth across systems. For each system,
compute:

    ratio = median_amg_fom / median_stream_triad_bandwidth

Then compute the fleet mean and sample standard deviation of these ratios.
Systems whose ratio deviates from the fleet mean by more than
`outlier_sigma_threshold` standard deviations (per config `[efficiency]`
section) have anomalous AMG performance relative to their memory subsystem,
warranting investigation.

## 4. Required Deliverables

All output files must be placed in `/app/results/`.

### 4.1 `audit_report.json`

| Key | Type | Description |
|-----|------|-------------|
| `total_runs` | int | Total run count in the database |
| `excluded_runs` | list | Objects with `run_id` (int) and `reason` (string) |
| `quality_flags` | list | Objects with `system`, `benchmark`, `flag`, `details` (all strings) — one entry per flagged system-benchmark pair per quality dimension |
| `fom_discrepancies` | list | Objects with `run_id` (int), `reported_fom` (float), `computed_fom` (float), `pct_error` (float, signed percentage) |

### 4.2 `performance_summary.json`

Top-level keys are system names. Each system maps benchmark names to:

| Field | Type | Description |
|-------|------|-------------|
| `median_fom` | float | Median FOM across valid runs |
| `mean_fom` | float | Mean FOM across valid runs |
| `std_fom` | float | Sample standard deviation |
| `ci_lower` | float | Lower bound of 95% CI for the mean |
| `ci_upper` | float | Upper bound of 95% CI for the mean |
| `valid_run_count` | int | Number of valid (non-excluded) runs |
| `flagged` | bool | True if any quality flag exists for this pair |

Use the t-distribution for confidence intervals (appropriate for small samples).

### 4.3 `efficiency_analysis.json`

| Key | Type | Description |
|-----|------|-------------|
| `stream_efficiency` | object | Keyed by system name, each with `measured_bandwidth` (float), `theoretical_peak` (float), `efficiency` (float) |
| `cross_benchmark_analysis` | object | Contains `amg_bandwidth_ratios` (object keyed by system name, float values), `fleet_mean` (float), `fleet_std` (float), `outlier_threshold_sigma` (float from config), `outliers` (list of system name strings) |

### 4.4 `ranking.json`

| Key | Type | Description |
|-----|------|-------------|
| `rankings` | list | Sorted descending by score. Each: `rank` (int), `system` (string), `score` (float), `flags` (list of quality concern strings, empty if clean) |

Scoring uses weighted geometric mean of per-benchmark median FOMs, normalized
against the reference system defined in config. Scores are computed from
independently calculated FOMs, not reported values.

## 5. Methodological Notes

- When specification documents conflict, the human-readable Markdown
  specification (`benchmark_specs.md`) is authoritative
- The database schema is intentionally undocumented; schema discovery is part
  of the evaluation
- Theoretical peak bandwidth values are recorded as STREAM measurement data
  in the database
- Use independently computed (not reported) FOM values for all statistical
  analyses and ranking computation
