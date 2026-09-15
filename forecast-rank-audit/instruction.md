A prediction market platform's scoring pipeline is under investigation. The platform's operational data spans three systems:

- **SQLite database** at `/app/data/platform.db` — forecaster profiles, event problems, probabilistic predictions, published Brier rankings, and IRT 2-PL model parameter estimates (item difficulties, discriminations, forecaster abilities)
- **Parquet market feed** at `/app/data/market_feed/market_ticks.parquet` — tick-level price history from the external exchange feed, with per-problem time series including `hours_before_close` for each tick
- **Scoring pipeline logs** at `/app/data/logs/scoring_pipeline.ndjson` — newline-delimited JSON execution logs from the automated scoring run that produced the published rankings and IRT estimates

Forecasters are disputing the published rankings and IRT ability estimates, alleging multiple independent errors in both the data and the pipeline logic. Cross-reference all three data sources and produce these files in `/app/results/`:

**`data_issues.json`** — Array of every data integrity problem discovered across all sources. Each entry: `{"issue_type": str, "description": str, "affected_entities": [...], "evidence": {...}}`

**`corrected_rankings.json`** — Rankings recomputed from clean data using at least two proper scoring rules and IRT 2-PL ability estimates (with the correct link function) as a third ranking method, combined via a rank-aggregation scheme. Array of objects: `username`, `final_rank`, plus one numeric score field per method used.

**`platform_bugs.json`** — Errors in the scoring pipeline identified by comparing independent computations against published values and analyzing the pipeline logs. Each entry: `{"bug_type": str, "description": str, "affected_entities": [...], "impact": str}`

**`irt_analysis.json`** — Re-estimated IRT 2-PL item and person parameters using the correct link function. Object containing: `item_parameters` (array of `{problem_id, difficulty, discrimination}`), `abilities` (array of `{username, ability}`), and `published_comparison` describing how and why your estimates diverge from the published values.

**`robustness.json`** — Rank stability analysis across all scoring methods used. Object with `rank_variance` (mapping username to variance of that forecaster's rank across methods) and `sensitive_forecasters` (usernames whose rank variance exceeds the median).