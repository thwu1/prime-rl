An SQLite database at `/app/data/benchmark.db` contains raw evaluation data from a robotic manipulation benchmark: binary rollout outcomes for three models across 8 tasks under 16 conditions (one baseline plus 15 perturbations organized in a hierarchical category taxonomy), along with real-world validation trials. The database includes metadata tables and operational notes from the data collection team.

A prior analysis of this dataset was retracted after discrepancies were found in the aggregated statistics. The database itself has not been corrected — whatever issues exist in the raw data remain from the original ingestion process.

Build `/app/analyze.py` (executable via `python3 /app/analyze.py`) that audits the raw data for integrity issues, applies appropriate corrections, performs the required statistical analysis, and writes results to `/app/output/report.json`.

The output must conform to the JSON schema at `/app/data/output_schema.json`. The `/app/data/` directory also contains documentation specifying the required statistical methodology — examine all available materials before beginning your analysis.

The report must contain:

- Effect sizes with confidence intervals for each (model, perturbation) combination across all 15 non-baseline perturbations and all 3 models — 45 entries total, keyed as `<ModelName>_pert<id>` with fields for the statistic, CI bounds, perturbation name, and category
- Per-model mean effect sizes aggregated by perturbation category for each of the 6 non-baseline categories
- Correlation between simulation baseline and real-world success rates across all valid (model, task) pairs, with confidence interval bounds, p-value, and pair count
- A per-model composite robustness index