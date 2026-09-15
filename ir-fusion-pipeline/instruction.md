An information retrieval evaluation pipeline at `/app/` was built with Pyserini against a 60-document corpus of research abstracts (`/app/corpus/docs.jsonl`), 8 test queries (`/app/queries.tsv`), and graded relevance judgments (`/app/qrels.txt`, TREC format). A colleague's initial pipeline artifacts are present: a pipeline log (`/app/pipeline_log.txt`), an index (`/app/index_v1/`), a retrieval run (`/app/runs/baseline_v1.txt`), and an evaluation report (`/app/report_v1.json`).

Peer review found that the reported evaluation metrics do not reproduce when independently verified, the term-level analysis component failed — returning empty results for all documents despite the log claiming appropriate index configuration — and the pipeline is incomplete, evaluating only a single retrieval variant.

Investigate the existing pipeline artifacts, diagnose all root causes, and deliver a complete, verified evaluation suite.

**Deliverables:**

`/app/diagnosis.txt` — For each problem in the original pipeline, state what was claimed versus what is actually true, and explain the mechanism of failure.

`/app/index/` — A Lucene index built from `/app/corpus/docs.jsonl` that supports retrieval, raw document access, and document-level term vector extraction.

`/app/runs/` — Four TREC-format retrieval runs (1000 hits per query):
- `bm25_default.txt` — BM25 with k1=0.9, b=0.4
- `bm25_tuned.txt` — BM25 with an alternative parameterization demonstrating the effect of parameter tuning
- `bm25_expanded.txt` — BM25 augmented with pseudo-relevance feedback for query expansion
- `fused.txt` — Rank-level fusion combining the three runs above

`/app/results.json` — MAP and nDCG@10 for each run evaluated against `/app/qrels.txt`, values rounded to 4 decimal places:
```json
{"<run_name>": {"map": <float>, "ndcg_cut_10": <float>}, ...}
```

`/app/term_analysis.json` — For each query, the top-ranked document from the BM25 default run and the 5 terms contributing most to that document's BM25 relevance score, with their individual term-level weights:
```json
{"<query_id>": {"top_doc": "<doc_id>", "top_terms": [{"term": "<term>", "weight": <float>}, ...]}}
```