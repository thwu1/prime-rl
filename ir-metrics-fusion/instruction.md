Three passage retrieval systems (BM25, neural, TF-IDF) have been run against a set of queries with graded relevance judgments. Produce an evaluation report at `/app/report.json` that conforms exactly to the schema defined in `/app/schema.json` and contains numerically accurate results.

## Environment

- `/app/data/` — relevance judgments (`qrels.tsv`) and ranked passage lists from each retrieval system (`run_bm25.tsv`, `run_neural.tsv`, `run_tfidf.tsv`)
- `/app/eval/` — a Python evaluation codebase
- `/app/schema.json` — JSON schema specifying the required structure, fields, and computational methodology for the output report