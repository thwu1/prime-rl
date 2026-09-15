# NIST GenAI Text Challenge — Discriminator Evaluation Protocol (Excerpt)

## Context

The NIST GenAI Text Challenge evaluates AI systems across three tracks. In the
Discriminator track, systems analyze text narratives and produce:

- An **AI-likelihood score** (0 to 1): the system's estimate that the text is AI-generated
- A **believability score** (0 to 1): the system's prediction of what proportion of readers
  would believe the narrative's content

## Submission Format

Each discriminator submission is a JSON file containing team identification, the evaluation
set it was run against, and a list of per-narrative predictions.

Required top-level fields: `team`, `docker_id`, `input`, `prediction_list`, `execution_time`.

Each entry in `prediction_list` must include: `statement_id`, `ai_likelihood_score` (number
in [0, 1]), and `believability_score` (number in [0, 1]).

A submission is **invalid** if any required field is missing or any score is outside the
allowed range. Invalid submissions are excluded from metric computation but must appear
in the validation report.

## Evaluation Criteria

Discriminator performance is assessed on multiple dimensions:

### Discrimination Power
How effectively does the system separate AI-generated text from human-written text?
Quantified by the concordance probability: given a randomly chosen AI-generated
narrative and a randomly chosen human-written narrative, what is the probability
the AI-generated one receives the higher AI-likelihood score? Tied pairs contribute
half weight to concordance. A value of 1.0 indicates perfect separation; 0.5
indicates performance no better than chance.

When an evaluation set contains only one class (all human or all AI), this metric
cannot be computed and should be treated as undefined (`null`).

### Prediction Accuracy
How close are the predicted AI-likelihood values to the true labels? Measured by the
mean squared difference between each prediction and its corresponding ground truth
indicator (1 for AI-generated, 0 for human-written). Lower values indicate more
accurate predictions.

### Confidence Calibration
Are the predicted probabilities well-calibrated? Assessed by partitioning predictions
into equal-width confidence bins spanning [0, 1], then computing the weighted average
absolute difference between predicted confidence and observed positive frequency within
each bin. Scores of exactly 1.0 belong in the highest bin.

The binning granularity is controlled by the pipeline configuration (`ece_bins`).
Standard practice in the calibration literature uses decile binning (10 equal-width
bins).

### Believability Assessment
Aggregate statistics of predicted believability scores: overall mean, overall maximum,
and per-source-category means (human-authored vs AI-generated narratives separately).
Categories with no entries report `null`.

### Over-Deception
A system is flagged for over-deception when it systematically assigns higher
AI-likelihood scores to human-written text than to AI-generated text — performing
worse than random chance (concordance probability below 0.5).

### Composite Score
Overall quality combines discrimination power, prediction accuracy complement
(1 − Brier), and calibration complement (1 − ECE) with weights summing to 1. The
standard NIST weighting allocates 40% to discrimination, 30% to accuracy complement,
and 30% to calibration complement. Active weights are read from the pipeline
configuration. Higher composite scores indicate better overall performance.
Only defined when discrimination power can be computed.

## Output Requirements

The evaluation produces three output artifacts:

1. **Validation report** — keyed by submission filename stem, each entry containing
   `valid` (boolean) and `errors` (list of error descriptions)

2. **Metrics** — keyed by submission filename stem, each entry containing: `eval_set`,
   `team`, `n_predictions`, `auc_roc`, `brier_score`, `ece`, believability statistics,
   `over_deception`, and `composite_score`

3. **Rankings** — array of objects sorted by composite score descending, each containing
   `rank`, `name`, `team`, `eval_set`, `composite_score`, `auc_roc`, `brier_score`, `ece`.
   Exclude submissions with undefined composite scores.

All numeric values should be rounded to 6 decimal places.
