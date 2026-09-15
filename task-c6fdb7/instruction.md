The evaluation pipeline at `/app/` compares three retrieval systems (BM25, dense neural, learned sparse) using standard IR effectiveness metrics (nDCG@10, MAP@10, MRR, P@10), rank fusion strategies (RRF, CombSUM, CombMNZ), and statistical significance testing. The pipeline runs end-to-end but produces incorrect evaluation results due to multiple bugs spanning judgment aggregation, metric computation, and rank fusion.

The environment contains:
- `/app/evaluate.py` — Main evaluation pipeline
- `/app/fusion.py` — Rank fusion implementations
- `/app/config.yaml` — Configuration including significance test parameters
- `/app/data/` — Retrieval results in heterogeneous formats and a SQLite judgments database with multi-annotator graded relevance assessments
- `/app/README.md` — Data documentation and database schema
- `/app/schema.json` — Required output schema

Diagnose and fix all bugs in the pipeline. The bugs interact — some only become apparent after others are corrected. The pipeline also lacks the paired bootstrap significance testing between individual systems specified in the config, which must be implemented.

Produce `/app/results.json` conforming to the output schema with correct evaluation results.