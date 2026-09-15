# Refactoring Evaluation Reference

## Overview

This pipeline evaluates code refactoring quality by processing SARIF 2.1.0 static analysis results against OpenGrep rule definitions and test execution outcomes to compute composite quality metrics.

## Input Data

Each instance directory under `/app/data/instances/` contains:

- `rules_positive.yml` / `rules_negative.yml` — OpenGrep rule definitions in YAML format
- `positive.sarif` / `negative.sarif` — SARIF 2.1.0 scan outputs
- `test_results.json` — Test execution results with possible multiple runs

### Rule Counting

Rules are defined in OpenGrep/Semgrep YAML format with a top-level `rules` key containing a list of rule objects. Count only top-level entries under the `rules` key — sub-patterns within composite rules (e.g., items inside `pattern-either`) do not count as separate rules. A file with `rules: []` contributes 0 rules.

### SARIF 2.1.0 Rule Matching

A rule is **matched** if at least one qualifying SARIF result references it.

**Rule reference resolution:**

SARIF results reference rules via `ruleId` (a string matching a rule's `id` field) or `ruleIndex` (an integer index into the rules array of the appropriate tool component).

When `ruleIndex` is used, the target rules array is determined by the result's `rule.toolComponent` property:
- If `rule.toolComponent` is **absent**, resolve against `tool.driver.rules` in the same run.
- If `rule.toolComponent` is **present**, resolve against `tool.extensions[toolComponent.index].rules` in the same run, where `toolComponent.index` identifies the extension by its position in the `tool.extensions` array.

This is the standard SARIF 2.1.0 mechanism for tool extensions that define additional rules beyond the driver's built-in rules.

**Result qualification:**

Not all SARIF results represent actual rule matches. A result qualifies as a match only if ALL of the following hold:

1. Its `kind` property is `"fail"` or absent (the SARIF default is `"fail"`, meaning the rule detected a match)
2. Its `level` property is not `"none"` (the SARIF default is `"warning"`; `"none"` indicates an informational result)
3. Its `suppressions` array is empty or absent (results with non-empty `suppressions` are intentionally suppressed per the SARIF specification)

**Cross-run deduplication:**

A SARIF file may contain multiple `runs` entries. Merge results from all runs, deduplicating by resolved rule ID — a rule matched in multiple runs counts as one matched rule.

**Phantom rule detection:**

After extracting matched rule IDs from SARIF, cross-validate each ID against the corresponding rules YAML file. A resolved rule ID that does not appear as a top-level rule `id` in the YAML is a **phantom rule** — an artifact of stale or misconfigured analysis. Phantom rules must be:
- Counted per-instance (`phantom_positive_count`, `phantom_negative_count`)
- Excluded from all match counts and metric calculations

### Test Results Format

```json
{
  "runs": [
    {"passed": <int>, "failed": <int>, "skipped": <int>, "total": <int>},
    ...
  ],
  "error": <string|null>
}
```

Multiple runs capture test flakiness. Aggregation:
- `best_passed` = max(run.passed for all runs)
- `worst_failed` = min(run.failed for all runs)
- `total` = runs[0].total (consistent across runs)

## Metrics

The evaluation metric model is implemented in the reference source code at `/app/reference/evaluation_models.py`. Study that module to understand the precise metric computation logic — particularly the `RuleMetrics` class (IFR computation) and `TestMetrics` class (test validity).

The key metrics computed per instance are:

| Metric | Description |
|--------|-------------|
| `positive_ifr` | Fraction of desired patterns successfully introduced. Null when no positive rules exist. |
| `negative_ifr` | Fraction of undesired patterns successfully removed. Null when no negative rules exist. |
| `ifr` | Combined instruction following rate across positive and negative rules. |
| `test_valid` | Whether the test execution meets quality criteria. |
| `pass_score` | Binary: 1.0 if tests are valid, 0.0 otherwise. |
| `alignment` | Product of pass_score and IFR. Zero when tests are invalid. Null when IFR is null. |

## Aggregation

### Mean Metrics

Compute arithmetic means across all instances:
- `mean_ifr`, `mean_positive_ifr`, `mean_negative_ifr`: mean of all **non-null** values.
- `mean_pass`: mean of all `pass_score` values (never null).
- `mean_alignment`: mean of all **non-null** `alignment` values.

If all values are null, the mean is null.

### Bootstrap 95% Confidence Intervals

Compute bootstrap 95% CIs for `alignment`, `ifr`, and `pass`:

- Number of bootstrap samples: **10000**
- Random seed: **42** (use `numpy.random.RandomState(42)`)
- Method: percentile — 2.5th and 97.5th percentiles of bootstrap means
- Procedure: from N non-null values, sample N with replacement, compute the mean, repeat 10000 times
- If fewer than 2 non-null values exist for a metric, CI is `null`

## Required Database Schema

The pipeline must produce a SQLite database at `/app/results/evaluation.db` with a table `instance_metrics`:

| Column | Type |
|--------|------|
| `instance_name` | TEXT PRIMARY KEY |
| `positive_rules_total` | INTEGER |
| `positive_rules_matched` | INTEGER |
| `negative_rules_total` | INTEGER |
| `negative_rules_matched` | INTEGER |
| `positive_ifr` | REAL (nullable) |
| `negative_ifr` | REAL (nullable) |
| `ifr` | REAL (nullable) |
| `test_passed` | INTEGER |
| `test_failed` | INTEGER |
| `test_total` | INTEGER |
| `test_valid` | INTEGER (0 or 1) |
| `pass_score` | REAL |
| `alignment` | REAL (nullable) |
| `phantom_positive_count` | INTEGER |
| `phantom_negative_count` | INTEGER |

## JSON Output Format

Write to `/app/results/evaluation.json`:

```json
{
  "instances": {
    "<instance_directory_name>": {
      "positive_rules_total": <int>,
      "positive_rules_matched": <int>,
      "negative_rules_total": <int>,
      "negative_rules_matched": <int>,
      "positive_ifr": <float|null>,
      "negative_ifr": <float|null>,
      "ifr": <float|null>,
      "test_passed": <int>,
      "test_failed": <int>,
      "test_total": <int>,
      "test_valid": <bool>,
      "pass_score": <float>,
      "alignment": <float|null>,
      "phantom_positive_count": <int>,
      "phantom_negative_count": <int>
    }
  },
  "aggregate": {
    "mean_positive_ifr": <float|null>,
    "mean_negative_ifr": <float|null>,
    "mean_ifr": <float|null>,
    "mean_pass": <float>,
    "mean_alignment": <float|null>,
    "ci95_alignment": [<lower_bound>, <upper_bound>] | null,
    "ci95_ifr": [<lower_bound>, <upper_bound>] | null,
    "ci95_pass": [<lower_bound>, <upper_bound>] | null,
    "num_instances": <int>,
    "total_phantom_rules": <int>
  }
}
```

`test_passed` and `test_failed` in instance output must reflect `best_passed` and `worst_failed` from multi-run aggregation.
