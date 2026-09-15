A benchmark evaluation pipeline exists at `/app/` that must process AI model evaluation data from a SQLite metadata database, Parquet-formatted run results (queried via DuckDB), and CSV code-similarity annotations to produce a ranked leaderboard JSON.

The pipeline uses a three-stage architecture:
1. **DuckDB SQL extraction** (`/app/src/extract.sql`) — reads Parquet + SQLite data into intermediate format
2. **Python transform** (`/app/src/transform.py`) — computes pass@k metrics and contamination detection
3. **jq assembly** (`/app/src/assemble.jq`) — sorts, ranks, rounds, and produces final JSON output

The orchestrator at `/app/src/pipeline.py` coordinates these stages. The full specification is at `/app/docs/spec.md`.

The extraction stage has a working SQL implementation, but you must evaluate whether its statistical methods and NULL-handling semantics are correct for this benchmark's requirements. The transform stage has stub functions for the pass@k estimator and contamination detection algorithm that must be designed and implemented — the specification describes the requirements and references the relevant literature, but does not provide implementation formulas. The jq assembly stage has sort logic that may not match the output schema specification. The orchestration layer may not correctly forward all CLI arguments to downstream stages.

Complete the pipeline so that `python3 /app/src/pipeline.py` produces a correct leaderboard at `/app/output/leaderboard.json` conforming to the specification, including correct behavior for `--start-date` and `--end-date` time-window filtering.