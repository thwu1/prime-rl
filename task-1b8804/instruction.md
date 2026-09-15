Sokoban puzzle levels are stored in `/data/levels/`. These levels come from various contributors and have not been verified for correctness.

Sokoban rules: `#`=wall, `@`=player, `$`=box, `.`=goal, `+`=player on goal, `*`=box on goal. The player moves in 4 cardinal directions and can push (not pull) one box at a time into an empty cell.

Create the following in `/app/`:

**`audit.sh <directory>`** -- Examines every `.txt` file in the given directory. Writes `/app/audit_results.json` mapping each filename to `{"status": "<class>", "reason": "<why>"}` where class is `"solvable"`, `"unsolvable"`, or `"malformed"`. Must determine classification through structural and logical analysis of each level, not by attempting to solve and timing out.

**`solve.sh <level_file>`** -- Prints a valid solution to stdout using `{u,d,l,r,U,D,L,R}` (lowercase=move, uppercase=push). Must handle solvable levels up to 6 boxes on boards up to 20x20 within 180 seconds.

**`analyze.sh <level_file>`** -- Solves the level and produces:
- `/app/results.db`: SQLite3 table `solutions` (columns: `level_file TEXT, solution TEXT, num_moves INTEGER, num_pushes INTEGER, solved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`). Each call appends a row.
- `/app/viz/<basename>.dot`: Graphviz DOT digraph with `num_pushes + 1` nodes labeled with ASCII board states, edges labeled `push up/down/left/right`.
- `/app/viz/<basename>.svg`: SVG rendered via `dot -Tsvg`.

Installed tools: `graphviz`, `sqlite3`.

```
```