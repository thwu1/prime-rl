The evaluation pipeline at `/app/pipeline.py` was built to assess MS MARCO passage ranking systems. It processes run files from `/app/data/runs/` against relevance judgments in `/app/data/qrels.tsv`, computing retrieval metrics (MRR@10, NDCG@10, MAP@50, Recall@50), per-query MRR statistics, and pairwise statistical significance tests.

Quality review has determined that the pipeline contains multiple bugs producing incorrect evaluation results. The current (wrong) output is saved at `/app/pipeline_output.json`. The official MS MARCO evaluation script at `/app/ms_marco_eval.py` — which correctly computes MRR@10 — is available for cross-referencing.

Audit the pipeline, identify and fix all evaluation errors, and produce correct results at `/app/results.json`:

    python3 /app/pipeline.py --qrels /app/data/qrels.tsv --runs /app/data/runs/ --output /app/results.json

The corrected output must use the same JSON schema as `/app/pipeline_output.json`.