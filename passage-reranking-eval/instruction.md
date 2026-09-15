A BM25 passage reranking pipeline at `/app/pipeline/` targets a synthetic MS MARCO-format dataset stored in `/app/data/corpus.db` (SQLite). The pipeline's last execution (log at `/app/pipeline/last_run.log`) reports MRR@10 far below what a correct BM25 implementation should achieve on this data (≥ 0.30). The pipeline has multiple interacting bugs distributed across its modules (`tokenizer.py`, `index.py`, `bm25.py`, `run_pipeline.py`).

The SQLite database schema: `collection(pid INTEGER PRIMARY KEY, text TEXT)`, `queries(qid INTEGER PRIMARY KEY, text TEXT)`, `qrels(qid INTEGER, iter INTEGER, pid INTEGER, rel INTEGER)`, `candidates(qid INTEGER, pid INTEGER)`. The official MS MARCO MRR@10 evaluation script is at `/app/data/ms_marco_eval.py`. Pre-computed baseline runs (oracle, tfidf, random) in MS MARCO tab-separated format are in `/app/data/runs/`. A TREC-format qrels flat file is at `/app/data/qrels.tsv`.

Produce these outputs:

- `/app/output/bug_report.json` — `{"bugs": [{"file": "<module filename>", "description": "...", "fix": "..."}, ...]}` identifying each pipeline bug.
- `/app/output/bm25_run.tsv` — Corrected BM25 reranking in MS MARCO format (`qid\tpid\trank`, 1-indexed ranks).
- `/app/output/bm25_run.trec` — Same ranking in TREC format (`qid Q0 pid rank score tag`, space-delimited, tag=`bm25`, scores monotonically decreasing per query).
- `/app/output/metrics.json` — `{"oracle_run": {"MRR@10": float, "NDCG@10": float, "MAP": float, "Recall@10": float, "Recall@100": float}, "tfidf_run": {...}, "random_run": {...}, "bm25_run": {...}}`

The corrected BM25 must achieve MRR@10 ≥ 0.30 via the official eval script. Metric values must match reference computations within ±0.002.