A multi-tool scoring pipeline at `/app/` evaluates LLM performance on research code implementation tasks. It reads from a SQLite database at `/app/benchmark.db`, with supplementary data exports in CSV (`/app/data/csv/`) and NDJSON (`/app/data/ndjson/`) formats. Results should be written to `/app/output/analysis.json`. The evaluation methodology is specified in `/app/METHODOLOGY.md`.

The pipeline was deployed prematurely and produces incorrect results across multiple metrics. The current draft output is at `/app/output/draft_analysis.json`.

Three earlier prototypes from different team members are archived:
- `/app/pipelines/alpha.py` → `/app/outputs/alpha.json` (JSON format)
- `/app/pipelines/beta.py` → `/app/outputs/beta/` (CSV format — one file per metric section)
- `/app/pipelines/gamma.py` → `/app/outputs/gamma.json` (JSON format)

None of the prototypes is fully correct, and they do not cover all required metrics. The prototypes use different scoring approaches (count-based vs LOC-weighted), different contamination boundaries, different bootstrap parameters, and different output formats. Use the Makefile targets at `/app/Makefile` for cross-format comparison: `make schema` to explore the database, `make compare` and `make compare-beta` to view prototype outputs, `make reconcile` to cross-compare JSON and CSV prototypes using `jq`, `csvjson`, `mlr`, and `sqlite3`, and `make explore` to examine the CSV/NDJSON data exports with `csvsql` and `jq`.

Audit the scoring pipeline against the methodology specification and produce a correct and complete analysis at `/app/output/analysis.json`.