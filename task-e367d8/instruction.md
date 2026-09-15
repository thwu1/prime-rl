A Sokoban puzzle benchmark suite is configured at `/app/`. The SQLite database `/app/benchmark.db` defines the benchmark: which puzzles to solve, where they are stored, and quality constraints each solution must satisfy.

Puzzle collections reside under `/app/collections/` in different formats. A utility is available at `/app/tools/sokovalidate` for working with these formats and validating solutions — explore its `--help` for usage details. Use `sqlite3` to query the benchmark database and discover its schema.

Implement a solver and produce `/app/results.json` — a JSON array where each element has `target_id` (matching the database) and `solution` (a LURD string). LURD encoding: lowercase `u`/`d`/`l`/`r` for non-push moves, uppercase `U`/`D`/`L`/`R` for push moves. A solution is valid when replaying it from the initial state places every box on a goal. Each solution's push count must not exceed the per-target threshold recorded in the database.

At least 8 of the 10 benchmark targets must be solved with valid, threshold-compliant solutions.