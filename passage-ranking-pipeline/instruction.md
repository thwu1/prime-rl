You are working with a passage ranking evaluation pipeline at `/app/`.

The pipeline includes a passage corpus (`/app/data/collection.tsv`, format: PID\ttext), evaluation queries (`/app/data/queries.tsv`, format: QID\ttext), relevance judgments in TREC qrels format (`/app/data/qrels.tsv`, format: QID\t0\tPID\trelevance), and BM25-retrieved candidate passages (`/app/data/top100.tsv`, format: QID\tPID\tquery\tpassage, 100 candidates per query).

The evaluation script at `/app/eval/ms_marco_eval.py` is supposed to compute MRR@10 for a ranked run file against relevance judgments. However, it contains multiple bugs that produce incorrect metric values. Three reference runs with known correct MRR@10 scores are provided in `/app/eval/reference_runs/` and `/app/eval/reference_scores.json`.

Produce the following:

1. `/app/eval/ms_marco_eval_fixed.py` — A corrected evaluation script that reproduces the reference scores in `/app/eval/reference_scores.json` (within ±0.0001 tolerance) when evaluated against the corresponding reference run files using `/app/data/qrels.tsv`.

2. `/app/output/run.tsv` — A reranking of the candidates in `/app/data/top100.tsv` using Okapi BM25 scoring (with IDF computed over `/app/data/collection.tsv`). Output format: QID\tPID\tRANK with 1-based contiguous integer ranks, one line per candidate. The run must achieve MRR@10 ≥ 0.28 as measured by correct MRR@10 evaluation.

3. `/app/output/submission/metadata.json` — Submission metadata JSON with fields: `team`, `model_description`, `paper`, `code`, `type` (value must be either `"full ranking"` or `"reranking"`).

4. `/app/output/submission/dev.txt.bz2` — The run file from (2), bz2-compressed.