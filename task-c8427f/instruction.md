A SQLite database at `/app/sokoban.db` contains four Sokoban puzzles and one solution attempt per puzzle.

**Existing tables:**
- `levels(id INTEGER PRIMARY KEY, board TEXT)` — Puzzle boards in standard Sokoban notation: `#` wall, `@` player, `+` player-on-goal, `$` box, `*` box-on-goal, `.` goal, space is floor.
- `attempts(id INTEGER PRIMARY KEY, level_id INTEGER, moves TEXT)` — Move sequences using `u/d/l/r` for walking and `U/D/L/R` for pushing (player moves one cell; a push also moves the adjacent box one cell further in the same direction).

**Create these three tables in `/app/sokoban.db`:**

`analysis(level_id INTEGER PRIMARY KEY, attempt_valid INTEGER, first_error_move INTEGER, error_type TEXT)` — For each level's attempt: `attempt_valid` is 1 only if every move is legal and all boxes rest on goals after the final move, 0 otherwise. `first_error_move` is the 0-indexed position of the first illegal move, or NULL if no illegal move exists. A move is illegal if it walks into a wall or box, pushes when no box is at the destination, or pushes a box into a wall or another box. `error_type` is NULL for a fully valid attempt; otherwise a short description of why the attempt fails.

`solutions(level_id INTEGER PRIMARY KEY, moves TEXT)` — A complete, valid solution for each level. Replaying the move sequence from the initial state must leave every box on a goal.

`dead_positions(level_id INTEGER NOT NULL, row INTEGER NOT NULL, col INTEGER NOT NULL)` — Every simple dead position for each level. A floor cell is a simple dead position if a lone box placed there can never be pushed to any goal through any sequence of moves, assuming no other boxes and the player able to reach any needed adjacent cell.