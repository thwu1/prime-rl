A passage ranking evaluation pipeline at `/app/` produces incorrect MRR@10 scores. The custom evaluation script `/app/eval/msmarco_eval.py` contains multiple bugs, and its results have never been cross-validated against the standard `trec_eval` tool — whose C source sits uncompiled in `/app/trec_eval_src/`.

Four system runs in `/app/runs/` use different formats: BM25 (`bm25.tsv`, MS MARCO TSV), TF-IDF (`tfidf.tsv`, MS MARCO TSV with duplicate PIDs), KNRM (`knrm.txt.bz2`, bz2-compressed MS MARCO), and ELECTRA (`electra.trec`, TREC format). Relevance judgments with graded relevance grades are at `/app/data/qrels.txt`. Configuration (bootstrap parameters, disagreement threshold, output schema) is in `/app/config.json`. An SQLite database with pre-created schema is at `/app/results.db`.

## Requirements

**Compile trec_eval:** Build the trec_eval binary from C source at `/app/trec_eval_src/` so that `/app/trec_eval_src/trec_eval` is executable. Use it to compute `recip_rank.10` on runs (converting MS MARCO format runs to TREC format as needed).

**Fix the custom eval script** (`/app/eval/msmarco_eval.py`): The script has bugs affecting MRR@10 computation. Specifically: `MaxMRRRank` must be `10` (not 9); candidate array indexing must be zero-based (rank 1 at index 0); the MRR denominator must divide by the number of judged queries (from qrels), not the number of ranked queries; and the relevance filter must accept graded relevance (any `rel > 0`, not only `rel == 1`). After fixes, the script must produce correct MRR@10 matching trec_eval's output for every run.

**Populate `/app/results.db`:** The database has three pre-created tables:

- `per_query_scores` — insert per-query reciprocal rank scores from both evaluation tools for all four systems (`bm25`, `tfidf`, `knrm`, `electra`). The `tool` column must use labels `custom` (for the fixed Python eval script) and `trec_eval` (for the compiled binary). Each system-tool combination must cover all judged queries.
- `summary` — insert aggregate mean scores per system-tool combination (at least 8 rows: 4 systems x 2 tools).
- `disagreements` — insert any per-query scoring disagreements between the two tools that exceed the configured threshold.

**Produce `/app/output/audit_report.json`** conforming to the schema in `/app/config.json`. The report has three top-level keys:

- `systems`: array of 4 entries (one per system: `bm25`, `tfidf`, `knrm`, `electra`), **sorted by `mrr_at_10` descending**. Each entry has fields: `name` (string), `mrr_at_10` (float), `queries_ranked` (int), `ci_95_lower` (float), `ci_95_upper` (float). The 95% bootstrap confidence interval must be computed using the seed and iteration count from `/app/config.json` and must contain the point estimate with width between 0.001 and 0.2.
- `pairwise_significance`: all C(4,2)=6 pairwise comparisons. Each entry has: `system_a` (string), `system_b` (string), `delta_mrr` (float, equal to `mrr_at_10(system_a) - mrr_at_10(system_b)`), `p_value` (float in [0,1]), `significant_at_005` (boolean, true if `p_value < 0.05`).
- `cross_tool_validation`: one entry per system. Each entry has: `system` (string), `custom_mrr` (float from fixed eval script), `trec_eval_mrr` (float from compiled trec_eval), `match` (boolean, true if difference is below the configured disagreement threshold). All four systems must appear, and all must show `match: true` after fixing the eval script.