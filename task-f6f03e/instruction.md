Five SameGame board configurations are at `/app/boards/board_{0..4}.txt`. A reference game engine is at `/app/engine.py`.

Create `/app/solver.py` that accepts a board file path as its sole argument and writes a sequence of moves to stdout. Each move is a line with two space-separated integers `col row` (0-indexed, origin at bottom-left). Lines starting with `#` are ignored.

## SameGame Rules

The board is a 15x15 grid with 5 colors (integers 0-4). A move selects a cell belonging to a connected group of 2 or more same-colored cells (cardinal adjacency only). The entire group is removed, scoring `(group_size - 2)^2` points. After removal, remaining cells fall down within their column (gravity). Columns that become empty are collapsed to the left. The game ends when no groups of size >= 2 remain. Clearing the board completely awards a 1000-point bonus.

## Board File Format

15 lines of 15 space-separated integers. First line is the top row (row 14), last line is the bottom row (row 0). Coordinate (0, 0) is the bottom-left corner.

## Requirements

- `/app/solver.py` must produce valid move sequences
- Each individual board must score at least **1000** points
- Total score across all 5 boards must be at least **10000** points
- Each board must complete within 50 seconds