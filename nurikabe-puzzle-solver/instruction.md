The `ppbench` Python package (pencil-puzzle-bench) is installed in this environment. It provides tools for Nikoli-style pencil puzzles — NP-complete constraint satisfaction problems with deterministic verification via an embedded pzpr.js engine.

A pipeline at `/app/pipeline.py` is supposed to produce verified solutions for 8 target puzzles listed in `/app/targets.json`. It currently crashes on startup.

Your task: produce correct puzzle solutions by any means necessary.

Write results to `/app/results.json` as a JSON array. Each entry must have:
- `puzzlink_url` (string) — the target puzzle URL
- `puzzle_type` (string) — the puzzle variety identifier
- `solved` (bool) — whether the solution is correct
- `moves` (list of strings) — the sequence of pzpr.js move commands that solve the puzzle

At least **5 of 8** target puzzles must have correct solutions, spanning at least **3 distinct puzzle types**.

Entry point: `cd /app && python3 pipeline.py`