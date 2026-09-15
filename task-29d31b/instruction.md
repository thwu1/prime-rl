A Sokoban state-space analysis pipeline is partially configured at `/app/`. The SQLite database `/app/sokoban.db` stores 5 puzzle levels in a `levels` table. The `Makefile` defines pipeline stages (`solve` → `analyze` → `report`) but the computational components — `/app/solver.py` and `/app/analyzer.py` — are missing.

Create these components so that `make all` in `/app/` succeeds:

**Solver** (`/app/solver.py`): Extract levels from the database, find push-optimal solutions (fewest box pushes), and insert them into a `solutions` table with schema `(level_id INTEGER PRIMARY KEY, move_string TEXT, num_moves INTEGER, num_pushes INTEGER)`. Move strings use `u/d/l/r` for walks and `U/D/L/R` for pushes.

**Analyzer** (`/app/analyzer.py`): For each level, compute and insert into the database:

- `dead_squares(level_id, x, y)`: every non-goal floor cell from which a box can never be pushed to any goal, regardless of player position or number of moves.
- `state_metrics(level_id, reachable_states, dead_end_states, solution_depth, avg_branching_factor)`: exhaustive state-space metrics. A state is the pair (normalized player position, box configuration). The normalized player position is the lexicographically smallest cell the player can walk to without displacing any box. `reachable_states` = total unique states reachable from the initial configuration via legal pushes. `dead_end_states` = non-goal states with zero valid push successors. `solution_depth` = minimum pushes to reach the solved state. `avg_branching_factor` = mean number of distinct successor states across all non-goal reachable states.
- `deadlock_census(level_id, corner_deadlocks, freeze_deadlocks)`: `corner_deadlocks` = count of non-goal floor cells with walls on two perpendicular adjacent sides. `freeze_deadlocks` = count of 2x2 grid positions (by top-left corner) where at least one cell is a wall, at least two cells are non-goal floor, and all four cells are either wall or floor.

The Makefile's `report` target generates `/app/report.json` from the populated tables — it will succeed once the data is correct. Consult the Makefile and `/app/report_schema.json` for interface details.