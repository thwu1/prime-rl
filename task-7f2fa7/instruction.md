A prototype analysis pipeline at `/app/draft_analysis.py` evaluates three LLM-based HLS code generators across five hardware benchmarks using synthesis data from `/app/data/synthesis_results.json`. The pipeline produces incorrect results across multiple analysis sections.

Debug the prototype, identify all errors, and produce a corrected and extended pipeline at `/app/hls_analyzer.py` that writes results to `/app/output/analysis.json`. The output JSON must contain these top-level sections:

- **`pass_at_k`**: Correct pass@k values for k in {1, 5, 10} across compile, simulate, and synthesize stages, averaged per model across benchmarks.

- **`pareto_fronts`**: Correctly identified non-dominated design points per model-benchmark pair, sorted by ascending latency. Each point: `{latency_ns, area_luts, power_mw}`.

- **`hypervolumes`**: Hypervolume coverage for each model-benchmark Pareto front, plus per-model `average`.

- **`hypervolume_validation`**: Each model-benchmark entry: `{sweep_line, pymoo, abs_diff, passed}` with 0.1% relative tolerance. Include per-model `all_passed` and top-level `all_passed`.

- **`model_ranking`**: Composite ranking derived from the dataset metadata. Each entry: `{model, composite_score, rank}`.

- **`ranking_sensitivity`**: Robustness of the composite ranking across all valid weight configurations where each of the three weights is at least 0.1, varies in 0.1 increments, and the three weights sum to 1.0. Report: `total_combinations`, `ranking_counts` (comma-separated ranking string to count), `dominant_ranking` (list), `stability_fraction`.

Additionally, generate 3D Pareto front scatter plots as SVG using gnuplot (`/usr/bin/gnuplot`), one per model-benchmark pair at `/app/output/plots/pareto_<model>_<benchmark>.svg` with corresponding `.dat` data files in the same directory.