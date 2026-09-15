The evaluation pipeline at `/app/pipeline.py` combines four retrieval signals (URL matching, entity overlap, TF-IDF cosine similarity, and BM25) to assess table-text relatedness, fuses them via weighted Reciprocal Rank Fusion with cross-validated weight optimization, and reports standard IR metrics. It currently has bugs causing crashes and incorrect results, and is missing critical components.

Consult the full specification at `/app/SPEC.md` for mathematical definitions, function contracts, and output schemas.

`/app/pipeline.py` must expose these public functions: `load_data`, `serialize_table`, `compute_precision_at_k`, `compute_recall_at_k`, `compute_f1_at_k`, `compute_ndcg_at_k`, `compute_reciprocal_rank`, `compute_average_precision`, `reciprocal_rank_fusion` (accepting an optional `weights` dict parameter for per-method weighting), `create_grouped_folds`, `compute_bm25_scores`, and `optimize_rrf_weights`.

Running `python3 /app/pipeline.py` must produce four files in `/app/output/`:

- **`metrics.json`** — JSON object with keys: `p_at_5`, `r_at_5`, `f1_at_5`, `ndcg_at_5`, `p_at_10`, `r_at_10`, `f1_at_10`, `ndcg_at_10`, `p_at_20`, `r_at_20`, `f1_at_20`, `ndcg_at_20`, `mrr`, `map`, `best_threshold`. All numeric; bounded metrics in [0, 1].
- **`predictions.csv`** — CSV with columns `text_id`, `table_id`, `score`. Must cover every pair from `/app/data/pairs.csv` with scores in [0, 1].
- **`config.json`** — JSON object with keys: `methods` (list of strings including all four scoring methods), `weights` (dict mapping method name to optimized weight), `threshold` (float), `n_folds` (int), `k_values` (list of ints).
- **`comparison.json`** — JSON object with keys `uniform` and `optimized`, each containing `weights` (dict mapping each of the four method names to its weight) and `metrics` (dict with keys `f1_at_10`, `map`, `ndcg_at_10`, all in [0, 1]). The `uniform` section uses weight 1.0 for all methods.

Input data is at `/app/data/` (`tables.json`, `texts.json`, `pairs.csv`).