A combinatorial optimization game environment is set up at `/app/`. The game involves selecting and ordering visits to tourist sites on a city grid to maximize total collected value, subject to temporal and spatial constraints.

Study `/app/game.py` to understand the game rules, constraint validation, and scoring. Review `/app/evaluate.py` to understand the evaluation harness, the greedy baseline, and the benchmark report it produces.

Your deliverables, all required:

**`/app/solver.py`** — A Python module exporting a function `solve(sites_data: dict) -> list[int]`. The function receives a dictionary mapping site IDs (string or int keys) to property dicts and returns an ordered list of integer site IDs representing a feasible tour. Each invocation must:

- Save a formal optimization model in LP format to `/app/models/` (one `.lp` file per instance). Each LP file must contain an objective section (`Maximize` or `Minimize`), a `Subject To` section with constraints, a variable declaration section (`Binary`, `Integer`, or `General`), and an `End` marker.
- Return only integer site IDs with no duplicates, all referencing valid sites from the input.
- Complete within 45 seconds per instance.

**`/app/benchmark_report.json`** — Produced by running `python3 /app/evaluate.py` after your solver is in place. Must be a JSON object with:

- `"instances"`: an array of objects each containing `"name"` (string), `"solver_score"` (number), `"greedy_score"` (number), `"ratio"` (number), `"time_sec"` (number), `"tour_length"` (integer).
- `"aggregate"`: an object with keys `"total_solver"` (number), `"total_greedy"` (number), `"aggregate_ratio"` (number).

**Performance requirements:**

- All tours must be feasible (`evaluate_tour` returns a value >= 0).
- No tour may contain duplicate site visits.
- Every instance must yield a positive solver score (> 0).
- The aggregate solver score across all five instances must exceed the greedy baseline (from `game.greedy_solve`) by at least 30% (i.e., `aggregate_ratio` >= 1.3).
- Each instance must solve within 45 seconds.

Pre-generated instances (5 instances, 40 sites each) are in `/app/instances/`.