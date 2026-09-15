A document retrieval system at `/app/` is underperforming. An inverted index at `/app/index.json` was built from the document corpus in `/app/corpus/`. Test queries are in `/app/queries.tsv` (TSV: query-id, text) and ground-truth relevance judgments in `/app/qrels.txt` (TREC qrels format).

Three retrieval configurations deployed by a previous team are stored as TREC-format run files in `/app/runs/` (`run_A.txt`, `run_B.txt`, `run_C.txt`). None meet the effectiveness targets in `/app/targets.json`. Each suffers from a distinct deficiency that you must identify and explain.

A BM25/QLD retrieval tool is at `/app/tools/bm25_search.py` and an evaluation tool at `/app/tools/evaluate.py`. Run each with `--help` for usage.

Produce these deliverables in `/app/results/`:

- **`diagnosis.json`** — Object keyed by `run_A`, `run_B`, `run_C`. Each entry: `map`, `ndcg_cut_10`, `recall_1000` (floats), `meets_targets` (object mapping each metric to boolean), and `deficiency` (non-empty string describing the root cause).

- **`optimized_run.txt`** — TREC-format retrieval run covering all queries that achieves every target in `/app/targets.json`.

- **`metrics_comparison.json`** — Object mapping configuration names to `{map, ndcg_cut_10, recall_1000}`. Must contain the three baselines plus at least four additional configurations you evaluated.

- **`optimal_config.json`** — Object with `parameters` (object), `map`, `ndcg_cut_10`, `recall_1000` (floats), and `rationale` (string >= 30 chars explaining why this configuration was chosen over alternatives).