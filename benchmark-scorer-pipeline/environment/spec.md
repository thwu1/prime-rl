# Benchmark Analysis Output Specification
Version 2.1 — Internal Use

## Database
SQLite: `/app/benchmark.db`

Tables: `papers` (paper_id, title, repo_first_commit), `snippets` (snippet_id, paper_id, lines_of_code, function_name), `models` (model_id, knowledge_cutoff, is_open), `results` (model_id, snippet_id, with_paper, without_paper)

## Output File
`/app/output/analysis.json` — all floats rounded to 6 decimal places.

### scaled_pass1
Per-model success rate under the with_paper condition, weighted by lines of code. Maps model_id to float.

### contamination_safe_scaled_pass1
Same weighted metric restricted to snippets whose source paper's repository was created strictly after the model's training cutoff. Null when no snippets qualify. Maps model_id to float or null.

### paper_ablation_impact
Improvement in the weighted success rate attributable to providing paper context (with vs. without). Maps model_id to float.

### bootstrap_ci
95% CI for scaled_pass1 (with_paper) via paper-level stratified bootstrap. Parameters: `random.Random(2024)`, 10000 iterations, papers drawn from alphabetically-sorted ID list. Bounds at floor-index 2.5th/97.5th percentiles of sorted bootstrap distribution. Maps model_id to {"lower": float, "upper": float}.

### ranking
Models ordered by contamination_safe_scaled_pass1 descending. Fields: rank (1-indexed int, or null for unscored), model_id, contamination_safe_score (float or null). Null-scored models appear last.
