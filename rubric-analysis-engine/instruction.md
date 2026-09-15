A hierarchical rubric scoring system for evaluating research paper replications is broken across two legacy implementations that produce conflicting results. Your job is to determine the correct methodology, reconcile the tools, and produce accurate outputs.

## Environment

- `/app/data/rubrics.db` — SQLite database with rubric trees (adjacency list), binary leaf gradings, verified reference values (`verified_results`, `verified_agreement` tables), and agreement pairs.
- `/app/legacy/scorer.py` — Python scoring tool. Run `python3 /app/legacy/scorer.py --help` for subcommands.
- `/app/legacy/pipeline.sh` — Shell-based scoring pipeline using `sqlite3` recursive CTEs and `jq`. Run `bash /app/legacy/pipeline.sh` for usage.
- `/app/config/policy.yaml` — Scoring policy configuration defining required methodology parameters.
- `/app/docs/scoring_notes.md` — Internal documentation on the intended scoring methodology.

Both legacy tools produce incorrect or incomplete results. They disagree with each other and with verified reference values in the database in different ways. Determine which parts of each tool are correct and which are buggy, then produce the correct outputs.

## Objective

Produce the following output files at `/app/output/`. All floating-point values must be rounded to 6 decimal places.

### `/app/output/scores.json`

Correct root-level aggregate score for every rubric/grading combination in the database.

Format: `{"<rubric_name>/<grading_id>": <float>, ...}`

### `/app/output/sensitivity.json`

Effective weight of each leaf in each rubric — the root score increase when that leaf alone flips from 0 to 1. Within each rubric, ordered by value descending; ties broken by leaf ID ascending.

Format: `{"<rubric_name>": {"<leaf_id>": <float>, ...}, ...}`

### `/app/output/categories.json`

Per-task-category aggregate score for every rubric/grading combination, reflecting each leaf's structural importance in the tree.

Format: `{"<rubric_name>/<grading_id>": {"<category>": <float>, ...}, ...}`

### `/app/output/agreement.json`

Inter-rater reliability for every agreement pair defined in the database. The scoring policy configuration determines whether metrics should be weighted by each leaf's structural importance. `grading_id_1` is treated as predictions, `grading_id_2` as reference (positive class = 1).

Required metrics: `cohens_kappa`, `accuracy`, `precision`, `recall`, `f1`.

Format: `{"<pair_id>": {"cohens_kappa": <float>, "accuracy": <float>, "precision": <float>, "recall": <float>, "f1": <float>}, ...}`

### `/app/output/improvements.json`

For every rubric/grading combination where the root score is below 1.0, identify the top 3 currently-unsatisfied leaves whose satisfaction would yield the largest score improvement (or all unsatisfied if fewer than 3 exist). Report the resulting score if those leaves were flipped to 1.

Format: `{"<rubric_name>/<grading_id>": {"top_leaves": ["<id>", ...], "improved_score": <float>}, ...}` — leaves ordered by impact descending, ties broken by ID ascending.