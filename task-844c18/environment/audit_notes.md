# Audit Notes — Pipeline Evaluation Review

## Overview

An independent auditor ran the evaluation pipeline (`make report`) and compared its output against manually verified results. The pipeline produces substantially incorrect evaluation results. The discrepancies originate across multiple stages of the pipeline.

## Verified Agent-Level Results

| Agent | Expected Correct Tasks | Expected Correct Questions (out of 27) |
|-------|----------------------|--------------------------------------|
| agent_alpha | 7 / 8 | 26 / 27 |
| agent_beta | 4 / 8 | 23 / 27 |
| agent_gamma | 3 / 8 | 16 / 27 |

The pipeline currently reports far fewer correct answers for all agents.

## Observations

1. **Pipeline orchestration issues.** Running `make report` does not exercise all pipeline stages. Some intermediate outputs appear stale or absent. Review the Makefile target dependencies and the data paths passed to downstream stages to determine whether every stage is actually executed and whether each stage reads from the correct location.

2. **Vision-category questions are entirely absent from results.** The dataset contains 23 written questions and 4 vision questions across 8 capsules (7 capsules have written questions; 3 have vision questions). The pipeline's output reports zero vision questions for every capsule. The classification of questions into written vs. vision categories depends on patterns in the metric key names stored in the database — examine the actual key names to determine the correct rule.

3. **Numeric tolerance intervals are too narrow.** With only 3 replicate runs per experiment, the pipeline rejects several values that fall within reasonable experimental variance. The choice of probability distribution, variance estimator, and interval formula all influence the width of acceptance regions for small-sample stochastic data. The current methodology appears to conflate confidence intervals with prediction intervals.

4. **Submission format variations are silently dropped.** Some agents report values with percentage signs (e.g., `"94.5%"`) or as string-encoded numbers (e.g., `"3.14"`). These should be coerced to numeric values before comparison. Verify that the normalization stage is actually being invoked and that its coercion logic handles all observed formatting patterns.

5. **String comparison is overly strict.** Agents sometimes report string values with different capitalization (e.g., `"Gradient_Boosting"` vs `"gradient_boosting"`). The evaluator should treat these as matching.

6. **List comparison anomalies.** Some list comparisons fail even when the element values appear semantically identical. This may indicate type-level mismatches introduced during data extraction from the database. Investigate how list data is stored in the database and how the extraction process reconstructs list values.

7. **Task-level aggregation.** A capsule counts as a correct task in a category only if it has at least one question in that category and all questions in that category are answered correctly. Capsules with zero questions in a category should not inflate that category's correct-task count.

## Expected Output Schema

The corrected report must be written to `/app/evaluation_report.json`:

```json
{
    "agent_evaluations": {
        "<agent_name>": {
            "capsule_results": [
                {
                    "capsule_id": "<string>",
                    "correct_written_answers": "<int>",
                    "correct_vision_answers": "<int>",
                    "total_written_questions": "<int>",
                    "total_vision_questions": "<int>"
                }
            ],
            "summary": {
                "correct_tasks": "<int>",
                "total_tasks": "<int>",
                "correct_questions": "<int>",
                "total_questions": "<int>",
                "correct_written_tasks": "<int>",
                "total_written_tasks": "<int>",
                "correct_vision_tasks": "<int>",
                "total_vision_tasks": "<int>",
                "correct_written_questions": "<int>",
                "total_written_questions": "<int>",
                "correct_vision_questions": "<int>",
                "total_vision_questions": "<int>"
            }
        }
    },
    "rankings": {
        "by_correct_tasks": ["<agent_name>", "..."],
        "by_correct_questions": ["<agent_name>", "..."]
    }
}
```

Capsule ordering in results must match the order of experiments in the ground truth database. Agent names derive from submission filenames (without `.json`). Rankings are descending by the respective metric, with alphabetical tiebreaking (ascending).
