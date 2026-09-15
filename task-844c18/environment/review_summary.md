# Independent Review — Evaluation Pipeline Assessment

## Verified Scores

An independent reviewer manually verified the correct evaluation scores for each agent:

| Agent | Correct Tasks | Correct Questions (of 27) |
|-------|--------------|--------------------------|
| agent_alpha | 7 / 8 | 26 / 27 |
| agent_beta | 4 / 8 | 23 / 27 |
| agent_gamma | 3 / 8 | 16 / 27 |

Neither `evaluator.py` nor `evaluator_v2.py` produces these scores when run through the pipeline.

## Dataset Properties

- 8 capsules total: 7 with written questions, 3 with vision questions
- 23 total written questions, 4 total vision questions (27 total)
- 3 replicate runs per capsule
- Ground truth stored in `/app/capsules.db` (normalized relational schema across 5 tables)

## Reviewer Notes

The two evaluators differ in their distributional assumptions, interval formulas, and comparison logic. The reviewer confirmed that the correct methodology must:

- Use a statistical interval appropriate for predicting whether a **new observation** falls within the expected range of the experimental distribution — not for estimating a confidence region around the population mean
- Apply distributional assumptions appropriate for the available sample size (n=3)
- Use the variance estimator appropriate for a sample drawn from a larger population

The reviewer also noted that issues exist in the data pipeline independent of the evaluator logic — the Makefile orchestration, data extraction, and submission normalization stages each have problems that affect the final results regardless of which evaluator is used.

## Required Deliverables

### 1. Evaluation Report (`/app/evaluation_report.json`)

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

Capsule ordering must match database insertion order. Rankings are descending with alphabetical tiebreaking.

### 2. Methodology Specification (`/app/methodology.json`)

Document each statistical and data-handling choice using the controlled vocabulary below:

```json
{
    "distribution": "<one of: normal, t>",
    "degrees_of_freedom": "<formula as string, e.g. 'n-1'>",
    "variance_estimator": "<one of: population, bessel>",
    "interval_type": "<one of: confidence, prediction, tolerance>",
    "interval_half_width_formula": "<formula using variables: t, s, n>",
    "string_comparison": "<one of: case_sensitive, case_insensitive>",
    "vision_classification_rule": "<one of: fig_prefix, fig_substring>",
    "submission_preprocessing": ["<array from: percent_strip, string_to_number>"]
}
```
