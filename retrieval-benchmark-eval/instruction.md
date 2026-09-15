A retrieval evaluation pipeline at `/app/` produces results that disagree with reference evaluations. The pipeline benchmarks three systems across a heterogeneous IR benchmark (6 tasks, 3 domains).

- Benchmark data: `/app/data/benchmark/` (TREC-format qrels and run files per task)
- Pipeline script: `/app/evaluate.py` with config at `/app/config.json`
- Current (incorrect) output: `/app/output/current_report.json`

Audit the pipeline, identify all sources of error, and produce a corrected report at `/app/evaluation_report.json` containing:

- `per_task`: Metrics (`ndcg@10`, `map@100`, `mrr@10`, `recall@100`) per system (`system_alpha`, `system_beta`, `system_gamma`) per task, macro-averaged over queries
- `per_domain`: Metrics macro-averaged over tasks within each domain
- `overall`: Metrics macro-averaged over all tasks
- `system_ranking`: System names ordered by descending overall `ndcg@10`

nDCG uses exponential gain (2^rel - 1) with log2 discount. MAP, MRR, and Recall use binary relevance (rel >= 1). Unjudged documents are non-relevant.