A land cover classification assessment pipeline at `/app/lcnet/` contains multiple bugs and incomplete implementations across Python modules, SQL queries, and a Makefile. The package should be importable as `lcnet` and provide a working CLI via `python3 -m lcnet`.

Reference documentation for the intended LandCoverNet methodology is at `/app/reference/methodology.txt`. Sample data is at `/app/data/`.

The pipeline supports five CLI subcommands:

- `consensus <input.json> <output.json>` — merge multi-annotator pixel labels
- `assess <predictions.csv> <truth.csv> [--level N] [--db path]` — compute accuracy metrics (OA, kappa, per-class F1) at taxonomy levels 1, 2, or 3; when `--db` is given, persist results to a SQLite database
- `sample <features.csv> <n> [--seed S]` — select representative tiles; output JSON index list to stdout
- `score <submission.csv> <truth.csv> [--db path]` — validate and score probability submissions; output JSON with keys `valid`, `errors`, `score`; when `--db` is given, persist results to SQLite
- `report --db <path>` — query the results database; output JSON with keys `assessment_runs`, `by_level` (keyed by level string, each containing `count`, `mean_accuracy`, `mean_kappa`), `score_runs`, `mean_score`

Python API modules: `lcnet.consensus`, `lcnet.metrics`, `lcnet.sampling`, `lcnet.scoring`, `lcnet.storage`, `lcnet.taxonomy`.

A Makefile at `/app/Makefile` orchestrates batch pipeline operations. Targets `init-db`, `assess-sample`, `score-sample`, `report`, `pipeline`, and `clean` must all function correctly. The `pipeline` target chains the full sequence. `RESULTS_DB` and `DATA_DIR` must be overridable via command-line assignment (e.g. `make pipeline RESULTS_DB=/tmp/out.db`).

Diagnose and fix all issues across Python modules, SQL queries, and Makefile recipes. Complete any stub implementations. The package must remain at `/app/lcnet/`.
