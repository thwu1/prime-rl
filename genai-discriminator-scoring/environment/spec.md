# NIST GenAI Text Challenge — Discriminator Evaluation Specification

## Overview

This document specifies the evaluation protocol for scoring discriminator systems
in the NIST GenAI Text Challenge framework. Discriminators receive a mixed set of
human-written and AI-generated narratives and produce two scores per narrative:
an AI-likelihood score and a believability score.

## Input Data

### Ground Truth (`/app/data/ground_truth.json`)

Contains evaluation sets under `eval_sets`. Each eval set maps narrative IDs to:
- `true_source`: `"human"` or `"ai"`
- `human_believability`: float in [0, 1], human-annotated believability

### Discriminator Predictions (`/app/data/predictions/*.json`)

Each file follows the NIST discriminator output format:

```json
{
  "team": "<team_id>",
  "docker_id": "<team_id>/<image>:<version>",
  "input": "<eval_set_name>",
  "prediction_list": [
    {
      "statement_id": "<narrative_id>",
      "ai_likelihood_score": <float 0-1>,
      "believability_score": <float 0-1>
    }
  ],
  "execution_time": <float>
}
```

## Validation Rules

A prediction file is **invalid** if any of the following hold:
- Missing any required top-level field: `team`, `docker_id`, `input`, `prediction_list`, `execution_time`
- Any entry in `prediction_list` is missing `statement_id`, `ai_likelihood_score`, or `believability_score`
- Any `ai_likelihood_score` is not a number in [0, 1]
- Any `believability_score` is not a number in [0, 1]

Invalid files must be reported in the validation output but excluded from metric computation.

## Metrics

All metrics use the positive class = AI-generated (`true_source == "ai"`, binary label = 1).

### AUC-ROC (Area Under the ROC Curve)

Computed using the Wilcoxon-Mann-Whitney U-statistic:

    AUC = (C + 0.5 * T) / (P * N)

where C = number of concordant positive-negative pairs (positive score > negative score),
T = number of tied pairs, P = number of positives, N = number of negatives.

**Edge case**: If only one class is present in the eval set (P = 0 or N = 0),
AUC-ROC is undefined. Report as `null`.

### Brier Score

Mean squared error between predicted AI-likelihood and true binary label:

    Brier = (1/n) * Σ (ai_likelihood_score_i - y_i)²

where y_i = 1 if true_source is "ai", 0 if "human". Lower is better.

### Expected Calibration Error (ECE)

Partition predictions into 10 equal-width bins: [0, 0.1), [0.1, 0.2), ..., [0.9, 1.0].
Scores exactly equal to 1.0 go into the last bin.

For each non-empty bin b:
- `avg_confidence(b)` = mean of `ai_likelihood_score` values in the bin
- `accuracy(b)` = fraction of predictions in the bin where `true_source == "ai"`
- `weight(b)` = |b| / n (fraction of total predictions in this bin)

    ECE = Σ_b weight(b) * |avg_confidence(b) - accuracy(b)|

### Believability Statistics

For each valid prediction file, compute:
- `mean_believability`: mean of all `believability_score` values
- `max_believability`: maximum `believability_score`
- `mean_human_believability`: mean of `believability_score` for narratives where `true_source == "human"`
- `mean_ai_believability`: mean of `believability_score` for narratives where `true_source == "ai"`

If a category has no entries, report `null`.

### Over-Deception Flag

A discriminator exhibits "over-deception" when AUC-ROC < 0.5, meaning it
systematically assigns higher AI-likelihood to human text and lower to AI text.
This is worse than random and indicates a fundamentally inverted detector.

Set `over_deception = true` when AUC-ROC is not null and AUC-ROC < 0.5.

### Composite Score

    composite = 0.4 * AUC_ROC + 0.3 * (1 - Brier) + 0.3 * (1 - ECE)

Higher composite = better discriminator. Only computable when AUC-ROC is not null.

## Output Format

### `/app/output/validation_report.json`

```json
{
  "<filename_stem>": {
    "valid": true|false,
    "errors": ["<error description>", ...]
  }
}
```

### `/app/output/metrics.json`

```json
{
  "<filename_stem>": {
    "eval_set": "<set_name>",
    "team": "<team_id>",
    "auc_roc": <float|null>,
    "brier_score": <float>,
    "ece": <float>,
    "mean_believability": <float|null>,
    "max_believability": <float|null>,
    "mean_human_believability": <float|null>,
    "mean_ai_believability": <float|null>,
    "over_deception": true|false,
    "composite_score": <float|null>,
    "n_predictions": <int>
  }
}
```

Numeric values should be rounded to 6 decimal places.

### `/app/output/rankings.json`

Array of objects sorted by `composite_score` descending. Only entries with
non-null composite scores are included.

```json
[
  {
    "rank": 1,
    "name": "<filename_stem>",
    "team": "<team_id>",
    "eval_set": "<set_name>",
    "composite_score": <float>,
    "auc_roc": <float>,
    "brier_score": <float>,
    "ece": <float>
  }
]
```
