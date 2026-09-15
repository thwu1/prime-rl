Build an optimal solver for the 15-puzzle (4x4 sliding tile puzzle). Eight benchmark instances from Korf's 1985 canonical set are at `/app/puzzles.txt`. Each line:

    instance_id tile_at_pos0 tile_at_pos1 ... tile_at_pos15

Tile 0 is the blank. Goal state: `0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15` (blank upper-left, row-major order).

Write a solver that finds a minimum-length solution for every instance and writes `/app/results.json`:

```json
{
  "1": {"length": 57, "moves": "RRDLLU..."},
  "2": {"length": 55, "moves": "DRRULL..."}
}
```

`moves` is a string of U/D/L/R characters indicating the direction the blank moves per step. `length` must equal the number of characters in `moves`. Solutions must be provably optimal (minimum move count).

The instances include configurations with optimal solutions up to 59 moves. The 15-puzzle has 16!/2 ~ 10^13 reachable states with asymptotic branching factor ~2.13, so naive search and weak heuristics are computationally infeasible for the harder instances.