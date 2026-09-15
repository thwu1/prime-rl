A Python project at `/app/` has source modules `/app/src/engine.py` and `/app/src/evaluator.py` with a pytest suite in `/app/tests/`. The coverage.py configuration at `/app/.coveragerc` contains **five bugs** preventing branch coverage collection with per-test dynamic contexts.

All five bugs must be fixed. The corrected configuration should enable collecting a `.coverage` SQLite database with branch-level arc data and dynamic test-function contexts when the test suite is run under coverage.

Query the resulting `.coverage` database to produce two files in `/app/results/`:

**`test_file_map.json`**: JSON object mapping each non-empty test context to a sorted list of source file paths it covers, derived by joining `arc`, `context`, and `file` tables (excluding the empty-string context).

**`fragile_lines.json`**: JSON object mapping each source file path to a sorted, deduplicated list of line numbers covered by exactly one test context (excluding empty context), using positive `fromno` values from `arc`.

Both files: 2-space indentation, sorted keys.