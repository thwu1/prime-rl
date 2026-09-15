Two competing evaluator implementations at `/app/` assess whether automated agents correctly reproduced results from stochastic scientific experiments. Ground truth data from replicate experimental runs is stored in a normalized SQLite database at `/app/capsules.db`. Agent submissions are in `/app/submissions/`. The pipeline is orchestrated by `/app/Makefile`.

`/app/evaluator.py` uses a normal-distribution approach for numeric tolerance. `/app/evaluator_v2.py` was proposed as a replacement using a t-distribution approach. Neither produces correct results when run through the pipeline. An independent reviewer verified the expected scores and documented the requirements at `/app/review_summary.md`.

Analyze both evaluators and the full pipeline, determine the correct statistical methodology for small-sample stochastic reproducibility assessment, and produce:

1. `/app/evaluation_report.json` — correct evaluation results matching the reviewer's verified scores
2. `/app/methodology.json` — a methodology specification documenting each statistical and data-handling decision, using the controlled vocabulary defined in the review summary

The methodology specification must reflect principled choices — each decision will be verified against statistical theory for small-sample stochastic reproducibility assessment.