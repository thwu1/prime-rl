The PaperBench evaluation system at `/app/rubric_engine.py` scores research paper replications using hierarchical rubrics. The tool has correctness defects scattered across its subcommands — including in core library functions whose bugs cascade through multiple dependent commands — and one subcommand (`score-bounds`) that was scaffolded but never implemented.

The authoritative system specification is at `/app/spec.md`. Evaluation data (rubrics, grades, and judge prediction files) is in `/app/data/`.

Audit the full implementation against the specification, fix all defects, implement the missing subcommand, and create the analysis pipeline script at `/app/analyze.sh` as described in the specification. The pipeline must use `jq` for JSON processing and `sqlite3` for result persistence, producing a database at `/app/results.db`.

The final CLI tool must remain at `/app/rubric_engine.py`.