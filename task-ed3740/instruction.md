A SQLite database at `/app/sudoku_archive.db` contains an archive of completed 9×9 Sudoku grids and a task queue for various types of analysis. Explore the database schema to determine which grids have pending unavoidable-set analysis tasks and extract their grid strings. The database contains multiple analysis types and task statuses — only grids queued for the relevant analysis type with pending status should be processed.

An **unavoidable set** of a completed Sudoku grid G is a subset U of cells such that removing all clues in U from G yields a puzzle with multiple valid completions. An unavoidable set is **minimal** if no proper subset is also unavoidable. Any valid Sudoku puzzle must contain at least one clue from every unavoidable set of its solution grid.

A **clique** is a collection of pairwise disjoint unavoidable sets. The **Maximum Clique Number (MCN)** — the size of the largest clique — is a lower bound on the minimum number of clues for any puzzle from that grid.

For each qualifying grid, compute:

1. All minimal unavoidable sets of size exactly 4
2. All minimal unavoidable sets of size exactly 6
3. The MCN over all sets from (1) and (2) combined
4. One maximum clique witnessing the MCN

The `/app/tools/` directory contains a C source file implementing a fast Sudoku solution counter. Compile and integrate this tool into your verification pipeline — checking hundreds of unavoidable-set candidates requires a compiled solver for adequate performance.

Mathematical properties of minimal unavoidable sets:
- Always have even size; every digit in the set appears at least twice
- No minimal unavoidable set of size 2 exists
- Intersection with any row, column, or box is either empty or has ≥2 elements
- Size-4 sets contain exactly 2 distinct digits; size-6 sets contain exactly 3

Write results to `/app/results.json` as a JSON list ordered by `grid_id`:

```json
[
  {
    "grid_id": <database grid_id>,
    "ua4_count": <count of minimal UA sets of size 4>,
    "ua6_count": <count of minimal UA sets of size 6>,
    "mcn": <Maximum Clique Number>,
    "max_clique": [[cell_indices], ...],
    "ua4_sets": [[c1, c2, c3, c4], ...],
    "ua6_sets": [[c1, c2, c3, c4, c5, c6], ...]
  }
]
```

Cell indices: 0–80, left-to-right top-to-bottom. Sets sorted internally; set lists sorted lexicographically. `max_clique` entries must come from `ua4_sets` or `ua6_sets`.