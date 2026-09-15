A research pipeline for analyzing sudoku solution grids has been producing incorrect results. The pipeline components are at `/app/`:

- `analysis.db` — SQLite database containing the target grid (table `grids`), previous run results (table `clique_analysis` with `is_valid=0`), and diagnostic entries (table `run_log`)
- `tools/ua_finder.c` + `Makefile` — C implementation of a 2-digit unavoidable set finder using column permutation cycle analysis
- `tools/clique_finder.py` — Python script computing the maximum clique number (MCN) of the disjointness graph via Bron-Kerbosch
- `pipeline.log` — output from the most recent failed run
- `grid.txt` — the target sudoku solution grid (also stored in the database)

An **unavoidable set** of a sudoku solution grid is a subset of cells whose values can be rearranged to produce a different valid completion of the remaining cells. A set is **minimal** if no proper subset is also unavoidable. The **MCN** (maximum clique number) is the size of the largest collection of pairwise disjoint minimal unavoidable sets.

Diagnose why the pipeline is producing incorrect results, fix all issues in the tooling, and generate a correct and complete analysis. Your analysis must cover all minimal unavoidable sets of size at most 12 in the grid, including multi-digit trades that the current C tool does not handle.

Write results to `/app/results.json`:

```json
{
  "unavoidable_sets": [[cell_indices...], ...],
  "total_count": <int>,
  "mcn": <int>,
  "max_clique_indices": [<indices into unavoidable_sets array>],
  "clique_counts": {"2": <int>, "3": <int>, "4": <int>, "5": <int>}
}
```

Cell indices are 0–80 (row-major: row r, column c has index 9r+c). Each unavoidable set must be a sorted list of cell indices. The `clique_counts` field gives the total number of cliques of pairwise disjoint unavoidable sets at each size.

Also update the `clique_analysis` table in `/app/analysis.db`: insert a row for `grid_id=1` with the correct MCN, `max_clique_indices`, `clique_counts`, and `is_valid=1`.