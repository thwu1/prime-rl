An evaluation pipeline for a multi-task clinical trial challenge is producing incorrect team rankings. The pipeline scores six teams competing across three interconnected clinical tasks — tumor segmentation, cancer staging, and survival prognosis — and should produce a unified leaderboard with bootstrap confidence intervals.

The pipeline environment at `/app/` contains:

- Patient data and team submissions in a SQLite database (`/app/data/challenge.db`) with CSV exports under `/app/data/`
- Evaluation engine: `/app/evaluator/evaluate.py`
- Pipeline configuration: `/app/evaluator/config.toml`
- Runner script: `/app/evaluator/run_pipeline.sh`
- Methodology reference: `/app/docs/evaluation_notes.md`
- Known discrepancies: `/app/docs/validation_report.md`

Diagnose and correct all defects in the evaluation pipeline. The corrected pipeline must produce a valid leaderboard at `/app/output/leaderboard.json` conforming to the output schema in the evaluation notes.