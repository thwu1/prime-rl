Two research teams independently implemented an evaluation framework for measuring how well AI agents reproduce results from stochastic scientific code. Their implementations — `/app/evaluator_alpha.py` (Python) and `/app/evaluator_beta.R` (R) — produce different evaluation scores for the same inputs. Neither implementation is fully correct.

The authoritative evaluation methodology is described in `/app/paper_excerpt.md`. Ground truth data from multiple independent runs of 8 capsules is stored in the SQLite database `/app/ground_truth.db`. Agent result reports to evaluate are in `/app/agent_reports/`.

Produce a correct evaluation of all agents consistent with the paper's methodology and write three output files to `/app/results/`:

1. **`evaluation_summary.json`** — Top-level `agents` key. Each agent has a `summary` object with task-level and question-level accuracy counts disaggregated by category, and a `capsule_results` array with per-capsule correct/total counts by category.

2. **`prediction_intervals.json`** — Correctly-computed 95% interval bounds `[lower, upper]` for every numeric metric in every capsule, keyed by capsule ID then metric name.

3. **`sensitivity_audit.json`** — Analysis of how evaluation outcomes change under a different but related statistical interval method for numeric comparisons. Must contain: `method_comparison` (per-capsule/key bounds under both the paper's prescribed method and its closest methodological alternative); `fragile_results` (all agent results whose correctness verdict changes between the two methods); `robustness_scores` (per-agent fraction of answers correct under the primary method that remain correct under the alternative — 1.0 when an agent has zero correct answers under the primary method).