# Computational Reproducibility Evaluator -- Specification

## 1. Overview

Build a program that evaluates submitted answers against ground truth experimental results from multiple independent runs. The system uses prediction intervals to determine if submitted numeric answers are statistically consistent with the observed run results, and applies Grubbs' test for outlier detection to produce robust evaluations.

## 2. Input Files

### `/app/data/ground_truth.json`
JSON array of experiment objects:
```json
{
  "experiment_id": "<string>",
  "runs": [
    {"<question_key>": <value>, ...},
    ...
  ]
}
```
Each run is a dictionary with the same keys. Values may be numeric (`int`/`float`), `str`, or `list`.

### `/app/data/submissions.json`
JSON array of submission objects:
```json
{
  "submission_id": "<string>",
  "answers": {
    "<experiment_id>": {"<question_key>": <value>, ...},
    ...
  }
}
```

## 3. Type Classification

Classify each question key based on the type of its value in the **first run** of the experiment:
- `numeric`: Python `int` or `float` (but not `bool`)
- `string`: Python `str`
- `list`: Python `list`

## 4. Prediction Interval (Numeric Questions)

For each numeric question, compute a **95% prediction interval** for a new observation from the same population:

```
PI_lower = mean - t * s * sqrt(1 + 1/n)
PI_upper = mean + t * s * sqrt(1 + 1/n)
```

Where:
- `mean` = sample mean of the n run values
- `s` = sample standard deviation with Bessel's correction (ddof=1)
- `t` = critical value from Student's t-distribution: `t_{0.025, n-1}` (two-tailed 95%)
- `n` = number of runs

**Edge case**: If `s = 0` (all values identical), set PI = `[mean, mean]`.

## 5. Outlier Detection (Grubbs' Test)

For each numeric question where `n >= 3` and `s > 0`:

1. Compute Grubbs' statistic:
   ```
   G = max_i(|x_i - mean|) / s
   ```
   where the maximum is taken over all run values `x_i`.

2. Compute the critical value at significance level alpha = 0.05 (two-sided):
   ```
   t_c = t_{1 - alpha/(2*n), n-2}
   G_crit = ((n-1) / sqrt(n)) * sqrt(t_c^2 / (n - 2 + t_c^2))
   ```

3. If `G > G_crit`, the value with the maximum deviation from the mean is an outlier.

Apply **one iteration only** (detect at most one outlier per question).

If `s = 0` or `n < 3`, no outlier detection is performed (`outlier_detected` = false).

## 6. Robust Prediction Interval

If an outlier is detected for a question:
- Remove the outlier value from the run set
- Recompute the prediction interval using the remaining values (per Section 4)

If no outlier is detected, the robust PI equals the standard PI.

## 7. Submission Evaluation

For each question key present in the ground truth, evaluate the submitted value:

### Type Coercion (applied to submitted values only)
Before comparison, attempt to coerce the submitted value:
1. If the value is a string containing `%`, remove the `%` character
2. Attempt to convert the result to `float`
3. If conversion fails, keep the original value

### Numeric Comparison
- `standard_correct`: coerced submitted value falls within `[PI_lower, PI_upper]` (inclusive bounds)
- `robust_correct`: coerced submitted value falls within the robust PI (inclusive bounds)
- If the submitted value cannot be coerced to a number, both are `false`

### String Comparison
- Case-insensitive exact match: `str(submitted).lower() == str(ground_truth_run_0_value).lower()`
- `standard_correct` and `robust_correct` are identical

### List Comparison
- Direct equality: `submitted == ground_truth_run_0_value`
- `standard_correct` and `robust_correct` are identical

### Missing Keys
- If a question key from the ground truth is absent in the submission for that experiment, set `submitted` to `null`, `standard_correct` = false, `robust_correct` = false

## 8. Output Format

Write the evaluation to `/app/output/evaluation.json` with this exact structure:

```json
{
  "experiments": {
    "<experiment_id>": {
      "<question_key>": {
        "type": "<numeric|string|list>",
        "mean": "<float or null>",
        "std": "<float or null>",
        "standard_pi": {"lower": "<float>", "upper": "<float>"} ,
        "grubbs_statistic": "<float or null>",
        "grubbs_critical_value": "<float or null>",
        "outlier_detected": "<boolean>",
        "outlier_index": "<int or null>",
        "outlier_value": "<float or null>",
        "robust_pi": {"lower": "<float>", "upper": "<float>"}
      }
    }
  },
  "evaluations": {
    "<submission_id>": {
      "<experiment_id>": {
        "<question_key>": {
          "submitted": "<original value or null if missing>",
          "standard_correct": "<boolean>",
          "robust_correct": "<boolean>"
        }
      }
    }
  },
  "summary": {
    "<submission_id>": {
      "total_questions": "<int>",
      "standard_correct": "<int>",
      "robust_correct": "<int>",
      "standard_accuracy": "<float>",
      "robust_accuracy": "<float>"
    }
  }
}
```

**Rules for the experiments section:**
- For non-numeric questions: `mean`, `std`, `standard_pi`, `grubbs_statistic`, `grubbs_critical_value`, `outlier_index`, `outlier_value`, and `robust_pi` are all `null`
- `outlier_detected` is `false` for non-numeric questions and for numeric questions with `s = 0`
- For numeric questions where no outlier is detected, `robust_pi` must equal `standard_pi`
- `total_questions` in the summary counts all question keys across all experiments (defined by ground truth)
