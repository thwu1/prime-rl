# Evaluation Methodology
Version 3.1 — Scoring Committee Final

## Overview
This system evaluates LLM performance on research code implementation tasks.
The database `/app/benchmark.db` contains evaluation results for multiple models
tested on code snippets drawn from research papers. Explore its schema, tables,
and analytical views with `sqlite3 /app/benchmark.db`.

## §1 Primary Performance Metric — `scaled_pass1`
The primary metric quantifies total research code output by weighting each
implementation task proportionally to its complexity measured in lines of code.
This LOC-weighted formulation ensures that a model successfully implementing a
substantive 50-line algorithm contributes proportionally more than passing a
trivial 5-line helper. Map each model_id to a float.

## §2 Contamination Control — `contamination_safe_scaled_pass1`
Models may have been trained on data that includes benchmark source code.
A paper's source repository becomes publicly available at its `repo_first_commit`
date. The committee's decision on contamination boundary semantics — specifically,
whether a repository whose first commit date coincides exactly with a model's
knowledge cutoff is treated as safe or contaminated — is encoded in the database
view `v_model_paper_contamination`. Consult this view.

The contamination-safe metric excludes all snippets from potentially contaminated
papers and recomputes the §1 metric on the remaining snippets only. When exclusion
leaves no evaluable snippets for a model, the score must be explicitly null —
a zero score and an undefined score carry fundamentally different meanings.

Map each model_id to a float or null.

## §3 Context Ablation — `paper_ablation_impact`
Measure the marginal contribution of providing paper context during evaluation
using the same LOC-weighting methodology as §1. In this benchmark dataset every
model performs better with paper context — this property serves as a validity
check. Map each model_id to a float.

## §4 Confidence Estimation — `bootstrap_ci`
95% confidence intervals for the §1 metric via bootstrap resampling. The
resampling strategy must respect the hierarchical structure of the data:
snippets are nested within papers, and resampling individual snippets
independently would understate uncertainty by ignoring within-paper correlation.

Parameters: `random.Random(2024)` re-initialized per model, 10000 iterations,
resampling units drawn from the alphabetically-sorted list of paper IDs.
Percentile bounds at floor-indexed 2.5th and 97.5th percentiles of the sorted
bootstrap distribution.

Map each model_id to `{"lower": float, "upper": float}`.

## §5 Model Ranking — `ranking`
Rank all models by their contamination-safe performance (§2), best score first.
Models without a defined contamination-safe score receive a null rank and appear
at the end. Each entry: `{"rank": int_or_null, "model_id": str,
"contamination_safe_score": float_or_null}`.

## §6 Pairwise Statistical Comparison — `pairwise_significance`
To determine whether observed performance differences are statistically
meaningful, perform paired bootstrap hypothesis testing for all C(n,2) model
pairs. For each bootstrap iteration, resample the same set of papers for both
models under comparison and compute the LOC-weighted score difference (model_a
minus model_b). This paired design is essential: both models are evaluated on
identical tasks, so independent resampling would inflate variance and reduce
statistical power.

Apply Bonferroni correction for multiple comparisons at family-wise α=0.05.
For each pair, significance is determined by whether the Bonferroni-corrected
percentile interval of the score difference excludes zero (two-sided test).

Parameters: `random.Random(2024)` re-initialized per pair, 10000 iterations,
paper IDs drawn from the alphabetically-sorted list. Floor-indexed percentile
bounds at the Bonferroni-corrected significance level.

Model pairs are identified by alphabetically sorting the two model IDs and
joining with `_vs_`. Map `"modelA_vs_modelB"` to `{"model_a": str, "model_b":
str, "ci_lower": float, "ci_upper": float, "significant": bool}`.

## §7 Influence Diagnostics — `jackknife_stability`
Assess score stability via leave-one-paper-out (delete-one jackknife) analysis.
For each model, recompute the §1 LOC-weighted score excluding each paper in
turn. The delete-one jackknife standard error is:

  SE = sqrt((n-1)/n · Σᵢ(θ̂₍ᵢ₎ - θ̄₍.₎)²)

where n is the number of papers, θ̂₍ᵢ₎ is the LOC-weighted score excluding
paper i, and θ̄₍.₎ is the mean of all leave-one-out estimates. For each model,
identify the paper whose removal causes the largest absolute change in score.

Map model_id to `{"jackknife_se": float, "most_influential_paper": str,
"influence_magnitude": float, "leave_one_out_scores": {paper_id: float, ...}}`.

## Output Specification
Write to `/app/output/analysis.json` with top-level keys: `scaled_pass1`,
`contamination_safe_scaled_pass1`, `paper_ablation_impact`, `bootstrap_ci`,
`ranking`, `pairwise_significance`, `jackknife_stability`.
All float values rounded to 6 decimal places.
