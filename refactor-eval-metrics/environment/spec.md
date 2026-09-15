# Refactoring Evaluation Metrics Specification

## Overview

This document defines the metrics for evaluating code refactoring quality. The evaluation system processes SARIF 2.1.0 static analysis outputs and test execution results to compute composite quality scores across multiple benchmark instances.

## Input Data

Each instance directory under `/app/data/instances/` contains:

- `rules_positive.yml` — OpenGrep/Semgrep rules defining **desired** patterns (should appear after refactoring)
- `rules_negative.yml` — OpenGrep/Semgrep rules defining **undesired** patterns (should be absent after refactoring)
- `positive.sarif` — SARIF 2.1.0 output from scanning the refactored codebase with positive rules
- `negative.sarif` — SARIF 2.1.0 output from scanning the refactored codebase with negative rules
- `test_results.json` — Test execution results (possibly with multiple runs for flakiness detection)

### Rule YAML Format

Rules are defined in OpenGrep/Semgrep YAML format. Each file has a top-level `rules` key containing a list of rule objects:

```yaml
rules:
  - id: rule-identifier
    pattern: "<code pattern>"
    message: Description
    severity: INFO
    languages:
      - python
```

Rules may use `pattern`, `patterns`, `pattern-either`, or other composite pattern keys. **Count only top-level entries** under the `rules` key — sub-patterns within composite rules (e.g., items inside `pattern-either`) do not count as separate rules.

A file with an empty rules list (`rules: []`) or with `rules:` followed by nothing contributes **0 rules**.

### SARIF 2.1.0 Format

SARIF files follow the [SARIF 2.1.0 specification](https://docs.oasis-open.org/sarif/sarif/v2.1.0/). Key structural notes:

- A SARIF file may contain **multiple `runs`** entries. Results from all runs must be merged.
- Each run has `tool.driver.rules` (array of rule definitions) and `results` (array of matches).
- Results reference rules via one of:
  - `ruleId` — a string matching a rule's `id` field
  - `ruleIndex` — an integer index into the **same run's** `tool.driver.rules` array
- Both `ruleId` and `ruleIndex` are valid SARIF. Handle both correctly.
- A rule is considered **"matched"** if at least one result references it (by either method).
- When merging across multiple runs, **deduplicate** by rule ID: a rule matched in multiple runs counts as one matched rule.

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

Multiple runs capture test flakiness. Use the following aggregation:
- `best_passed` = max(run.passed for all runs)
- `worst_failed` = min(run.failed for all runs)
- `total` = runs[0].total (consistent across runs)

## Metrics

### Instruction Following Rate (IFR)

Let `positive_rules_matched` = number of distinct positive rules that have at least one SARIF result.
Let `total_positive_rules` = number of rules in `rules_positive.yml`.
Let `negative_rules_matched` = number of distinct negative rules that have at least one SARIF result.
Let `total_negative_rules` = number of rules in `rules_negative.yml`.

**Positive IFR** — fraction of desired patterns present:
```
positive_ifr = positive_rules_matched / total_positive_rules
```
Returns `null` if `total_positive_rules == 0`.

**Negative IFR** — fraction of undesired patterns successfully removed:
```
negative_avoided = total_negative_rules - negative_rules_matched
negative_ifr = negative_avoided / total_negative_rules
```
Returns `null` if `total_negative_rules == 0`.

**Combined IFR**:
```
ifr = (positive_rules_matched + negative_avoided) / (total_positive_rules + total_negative_rules)
```
Returns `null` if `(total_positive_rules + total_negative_rules) == 0`.

### Test Validity and Pass Score

Tests are **valid** if ALL of the following hold:
1. `total >= 10`
2. `best_passed / total >= 0.3`
3. `error` is `null`

**Pass score**: `1.0` if valid, `0.0` otherwise.

### Alignment Score

```
alignment = pass_score * ifr
```

Alignment is `0.0` when tests are invalid (regardless of IFR).
Alignment is `null` if IFR is `null`.

## Aggregation

### Mean Metrics

Compute the arithmetic mean of each metric across all instances:
- `mean_ifr`: mean of all non-null `ifr` values
- `mean_positive_ifr`: mean of all non-null `positive_ifr` values
- `mean_negative_ifr`: mean of all non-null `negative_ifr` values
- `mean_pass`: mean of all `pass_score` values
- `mean_alignment`: mean of all non-null `alignment` values

If all values for a metric are null, the mean is `null`.

### Bootstrap 95% Confidence Intervals

Compute bootstrap 95% CIs for `alignment`, `ifr`, and `pass`:

- Number of bootstrap samples: **10000**
- Random seed: **42** (use `numpy.random.RandomState(42)`)
- Method: percentile — 2.5th and 97.5th percentiles of bootstrap means
- Procedure: from N instance values, sample N values with replacement, compute the mean, repeat 10000 times

If fewer than 2 non-null values exist for a metric, CI is `null`.

## Output Format

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
      "alignment": <float|null>
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
    "num_instances": <int>
  }
}
```

`test_passed` and `test_failed` in the output should reflect `best_passed` and `worst_failed` from the multi-run aggregation.
