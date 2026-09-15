Puzzle instances for the "Undead" game (from Simon Tatham's Portable Puzzle Collection) are stored as compact game description strings in `/app/puzzles/`. A C-based verification toolkit is provided in source form at `/app/tools/` with a Makefile. Build it, then use its commands (`info`, `decode`, `verify`) to explore the encoding format and the puzzle mechanics. A solved example pair is in `/app/examples/`.

Create `/app/solver.py` that reads each game description file in `/app/puzzles/` and `/app/generated/`, solves the puzzle, and writes completed grids (one row per line, preserving mirror characters) to `/app/solutions/` with matching filenames. Must handle grids up to 8x8 within 60 seconds per puzzle.

Create `/app/generator.py` that produces new Undead puzzles with guaranteed unique solutions. It must write the following to `/app/generated/` in the standard game description format:
- `gen_4x4.txt`: 4x4 grid with at least 5 mirrors
- `gen_5x5.txt`: 5x5 grid with at least 8 mirrors
- `gen_7x7.txt`: 7x7 grid with at least 20 mirrors

Each generated puzzle must have exactly one valid solution. The generator must verify solution uniqueness before accepting a puzzle.

Create `/app/validate.sh` that builds the C tool if needed, runs the generator, runs the solver on all puzzles (provided and generated), and cross-validates every solution using the compiled verification tool. Exit 0 only when all solutions pass.

Run `bash /app/validate.sh` to produce and verify everything.