# Reproducibility Scoring Pipeline

## Overview
This pipeline evaluates how well AI agents reproduce results from scientific experiments.
Each experiment has been run multiple times independently to establish ground truth.
Agent submissions are scored based on whether their reported values are statistically
consistent with the observed distribution of experimental run results.

## Data

### `/app/data/experiments.json`
Array of experiments. Each has an `experiment_id` and an array of `runs` — dictionaries
with consistent keys across runs. Values may be numeric (int/float), string, or list.

### `/app/data/submissions.json`
Array of agent submissions. Each has a `submission_id` and an `answers` object mapping
experiment IDs to answer dictionaries with the same keys as the experimental runs.

### `/app/data/validation.csv`
Manually verified correct aggregate scores for each submission. Use this to confirm
your fixes produce the right results.

## Pipeline
`/app/pipeline/evaluator.py` reads the data, performs statistical analysis on experiment
runs, evaluates each submission against the analysis, and writes results to
`/app/output/results.json`.

## Scoring
The pipeline uses statistical methods to determine if an agent's reported numeric value
is consistent with the observed distribution of experimental runs. It also performs
outlier analysis to produce robust (outlier-adjusted) evaluations alongside standard
ones. Non-numeric answers (strings and lists) are compared directly against the
reference run.

## Output Format
The output JSON contains three sections:
- `experiments`: Per-experiment, per-question statistical analysis
- `evaluations`: Per-submission, per-question correctness judgments
- `summary`: Aggregate accuracy scores per submission

## Known Issue
The pipeline is currently producing incorrect evaluation scores. The correct aggregate
scores are in `validation.csv` for reference.
