# Reproducibility Evaluation Specification

## Overview

This document specifies how to evaluate agent-reported results from computational
reproducibility tasks against ground truth obtained from multiple independent runs
of scientific code.

## Input Format

### Ground Truth (`ground_truth.json`)

A JSON array of capsule objects. Each capsule has:

- `capsule_id` (string): Unique identifier for the capsule.
- `field` (string): Scientific discipline.
- `language` (string): Programming language.
- `results` (array of objects): Results from N independent runs. Every object in
  the array has the same set of keys. Values may be numeric (int/float), string,
  or list.

### Agent Reports (`agent_reports/<agent_name>.json`)

Each file represents one agent's evaluation results:

```json
{
  "capsule_results": [
    {
      "capsule_id": "<capsule_id>",
      "result_report": {
        "<key1>": "<value1>",
        ...
      }
    },
    ...
  ]
}
```

Reported values may be strings, numbers, or lists. String representations of
numbers (e.g. `"0.95"`) and values with trailing percent signs (e.g. `"45.2%"`)
are common.

## Evaluation Rules

### 1. Type Classification

Classify each result key by the type of its value in the **first** run:

| Python type      | Category  |
|------------------|-----------|
| `int` or `float` | Numeric   |
| `str`            | String    |
| `list`           | List      |

### 2. Vision vs. Written Questions

A key is a **vision question** if the substring `fig` appears **anywhere** in
the key name (case-sensitive match on the substring `fig`). All other keys are
**written questions**.

Examples:
- `"fig_roc_auc"` → vision (starts with `fig`)
- `"confusion_matrix_fig"` → vision (`fig` appears in the key)
- `"accuracy"` → written (no `fig` substring)

### 3. Numeric Evaluation — 95% Prediction Intervals

For each numeric key, compute the **95% prediction interval** from the ground
truth runs:

1. Sample mean:  `μ = (1/n) × Σ xᵢ`
2. Sample standard deviation (Bessel-corrected):
   `s = sqrt( (1/(n−1)) × Σ(xᵢ − μ)² )`
3. Critical value from Student's t-distribution (two-sided, 95%):
   `t* = t₀.₉₇₅,  n−1`
   (i.e., the 97.5th percentile of the t-distribution with n−1 degrees of
   freedom — this gives a **two-sided** 95% interval).
4. Prediction interval:  `μ  ±  t* × s × sqrt(1 + 1/n)`

> **Important**: This is a **prediction interval**, not a confidence interval.
> The factor under the square root is `1 + 1/n`, not `1/n`.

A reported numeric value is **correct** if it falls within `[lower, upper]`
(inclusive on both sides).

**Edge case — zero variance**: When all N runs produce identical values (`s = 0`),
the prediction interval collapses to `[μ, μ]`. A reported value is correct if and
only if it equals μ exactly.

### 4. String Evaluation

**Case-insensitive** exact match:

```
correct  ⟺  str(reported).lower() == ground_truth.lower()
```

### 5. List Evaluation

Exact match against the first run's value:

```
correct  ⟺  reported == ground_truth[0][key]
```

### 6. Value Coercion

Before comparing a reported value against ground truth, apply coercion:

1. If the value is already `int` or `float`, use it directly.
2. If the value is a string:
   a. Strip leading/trailing whitespace.
   b. If the string ends with `%`, remove the trailing `%`.
   c. Attempt to parse as `float`.
   d. If parsing fails, keep the original string.
3. All other types: use as-is.

### 7. Missing Keys

If a ground-truth key does not appear in the agent's report, it is counted as
**incorrect** (adds to the total but not to the correct count).

## Output Format

The evaluator must produce two files in the output directory.

### `evaluation_summary.json`

```json
{
  "agents": {
    "<agent_name>": {
      "capsule_results": [
        {
          "capsule_id": "...",
          "correct_written": <int>,
          "correct_vision": <int>,
          "total_written": <int>,
          "total_vision": <int>
        },
        ...
      ],
      "summary": {
        "correct_tasks": <int>,
        "total_tasks": <int>,
        "correct_questions": <int>,
        "total_questions": <int>,
        "correct_written_tasks": <int>,
        "total_written_tasks": <int>,
        "correct_vision_tasks": <int>,
        "total_vision_tasks": <int>,
        "correct_written_questions": <int>,
        "total_written_questions": <int>,
        "correct_vision_questions": <int>,
        "total_vision_questions": <int>
      }
    }
  }
}
```

### `prediction_intervals.json`

```json
{
  "<capsule_id>": {
    "<numeric_key>": [<lower_bound>, <upper_bound>],
    ...
  },
  ...
}
```

Only numeric keys are included. Bounds are floats.

### Aggregate Scoring Definitions

- **Correct task**: A capsule where `correct_written == total_written` **AND**
  `correct_vision == total_vision`.
- **Correct written task**: A capsule where `correct_written == total_written`
  **AND** `correct_written > 0`.
- **Correct vision task**: A capsule where `correct_vision == total_vision`
  **AND** `correct_vision > 0`.
- **Total written tasks**: Count of capsules where `total_written > 0`.
- **Total vision tasks**: Count of capsules where `total_vision > 0`.
