# Reproducibility Evaluation Protocol Specification

## Overview

This document specifies the evaluation protocol for assessing computational reproducibility of scientific code. Given ground truth results from multiple stochastic runs and reported results from agents, the system must determine which reported answers are correct and produce aggregate evaluation metrics.

## Data Format

### Ground Truth (`/app/ground_truth.json`)

A JSON array of capsule objects. Each capsule represents a scientific computing experiment:

```json
[
  {
    "capsule_id": "<string>",
    "field": "<string>",
    "language": "<string>",
    "results": [
      { "<question_key>": <ground_truth_value>, ... },
      { "<question_key>": <ground_truth_value>, ... },
      ...
    ]
  }
]
```

The `results` array contains result objects from `n` independent runs. All result objects within a capsule share identical keys. Values can be numeric (`int` or `float`), `str`, or `list`.

### Agent Submissions (`/app/submissions/<agent_name>.json`)

Each agent's file contains:

```json
{
  "capsule_results": [
    {
      "capsule_id": "<string>",
      "result_report": { "<question_key>": <reported_value>, ... }
    }
  ]
}
```

Reported values may be in any format. The evaluation must handle type coercion as specified below.

## Answer Type Classification

Answer types are determined by examining values in the **first** ground truth run (`results[0]`):

- **Numeric**: the value is an instance of `int` or `float`
- **String**: the value is an instance of `str`
- **List**: the value is an instance of `list`

## Question Category Classification

Each question key is classified into one of two categories:

- **Vision**: the key contains the substring `fig`
- **Written**: all other keys

These categories are used to compute separate accuracy metrics.

## Reported Value Preprocessing

Before comparison, preprocess each value in the agent's `result_report` as follows:

```
For each key in result_report:
    Try:
        1. If the value contains the character '%', remove all '%' characters
        2. Convert the value to float
    On any exception:
        Leave the value unchanged
```

This handles cases where agents report numeric values as strings (e.g., `"3.14"`), with percentage signs (e.g., `"94.5%"`), or as non-numeric strings that should remain as-is. The entire preprocessing for each key is wrapped in a single try/except — if any step fails, the original value is preserved.

## Evaluation Methods

### Numeric Values

Use **95% prediction intervals** based on the Student's t-distribution. A prediction interval estimates the range in which a **new observation** from the same process is expected to fall, accounting for both sampling uncertainty and inherent process variability.

Given ground truth values `[x_1, x_2, ..., x_n]` from `n` independent runs:

1. **Sample mean**: `x_bar = (1/n) * sum(x_i)`
2. **Sample standard deviation** (with Bessel's correction): `s = sqrt( (1/(n-1)) * sum((x_i - x_bar)^2) )`
3. **t-value**: `t = t_{0.975, n-1}` — the 97.5th percentile of the Student's t-distribution with `n-1` degrees of freedom
4. **Prediction interval bounds**:
   - `Lower = x_bar - t * s * sqrt(1 + 1/n)`
   - `Upper = x_bar + t * s * sqrt(1 + 1/n)`

A reported numeric value is **correct** if and only if: `Lower <= reported_value <= Upper`

**Important**: When all ground truth runs produce identical values (`s = 0`), the prediction interval collapses to a single point. In this case, only an exact match is accepted.

### String Values

Compare the reported value against the **first** ground truth run (`results[0]`):

1. Convert both the reported value and ground truth value to strings
2. Convert both to lowercase
3. The answer is **correct** if the lowercase strings are equal

### List Values

Compare the reported value against the **first** ground truth run (`results[0]`):

- Use direct equality comparison (order-sensitive, element-wise)
- The answer is **correct** if the lists are equal

### Missing or Extra Keys

- If the agent's `result_report` is missing a key that exists in ground truth, that question counts as **incorrect** (the correct count is simply not incremented).
- If the agent's `result_report` contains keys not present in ground truth, those extra keys are silently ignored.

## Aggregation

### Per-Capsule Metrics

For each capsule in each agent's evaluation, compute:

| Metric | Description |
|--------|-------------|
| `correct_written_answers` | Number of correctly answered **written** questions |
| `correct_vision_answers` | Number of correctly answered **vision** questions |
| `total_written_questions` | Total number of written questions in this capsule |
| `total_vision_questions` | Total number of vision questions in this capsule |

### Per-Agent Summary Statistics

| Metric | Definition |
|--------|------------|
| `correct_tasks` | Number of capsules where **all** written answers are correct **and** all vision answers are correct |
| `total_tasks` | Total number of capsules |
| `correct_written_tasks` | Number of capsules where all written answers are correct **and** the capsule has at least one written question |
| `total_written_tasks` | Number of capsules with at least one written question |
| `correct_vision_tasks` | Number of capsules where all vision answers are correct **and** the capsule has at least one vision question |
| `total_vision_tasks` | Number of capsules with at least one vision question |
| `correct_written_questions` | Sum of `correct_written_answers` across all capsules |
| `total_written_questions` | Sum of `total_written_questions` across all capsules |
| `correct_vision_questions` | Sum of `correct_vision_answers` across all capsules |
| `total_vision_questions` | Sum of `total_vision_questions` across all capsules |
| `correct_questions` | `correct_written_questions + correct_vision_questions` |
| `total_questions` | `total_written_questions + total_vision_questions` |

**Note on `correct_tasks` vs `correct_written_tasks`**: A capsule with zero written questions where all (zero) vision questions are trivially "all correct" **does** count toward `correct_tasks` (since `0 == 0` is true for both categories). However, it does **not** count toward `correct_written_tasks` because it fails the `>= 1 written question` requirement.

### Rankings

Rank agents in descending order by:

1. **`by_correct_tasks`**: Number of fully correct capsules. Ties broken alphabetically (ascending).
2. **`by_correct_questions`**: Total number of correct questions. Ties broken alphabetically (ascending).

## Output Format

Write the evaluation report to `/app/evaluation_report.json` with the following structure:

```json
{
    "agent_evaluations": {
        "<agent_name>": {
            "capsule_results": [
                {
                    "capsule_id": "<string>",
                    "correct_written_answers": <int>,
                    "correct_vision_answers": <int>,
                    "total_written_questions": <int>,
                    "total_vision_questions": <int>
                }
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
    },
    "rankings": {
        "by_correct_tasks": ["<agent_name>", ...],
        "by_correct_questions": ["<agent_name>", ...]
    }
}
```

The `capsule_results` array must preserve the same ordering as the capsules in `ground_truth.json`. Agent names are derived from submission filenames with the `.json` extension removed.
