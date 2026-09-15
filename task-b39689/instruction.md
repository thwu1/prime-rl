Build a compiled Sokoban puzzle solver and its build system in `/app/`.

**Deliverables:**
- `/app/solver` — a compiled ELF binary (not an interpreted script)
- A build system (`/app/CMakeLists.txt` or `/app/Makefile`) that can rebuild the solver from C/C++ source code present in `/app/`

**Solver interface:**
- Takes one argument: path to an XSB puzzle file
- Prints a valid LURD solution string to stdout (single line)
- Returns exit code 0 on success

**LURD format:** Characters `u/U` (up), `d/D` (down), `l/L` (left), `r/R` (right). Uppercase conventionally indicates a push; all-lowercase solutions are accepted.

**XSB cell characters:** `#` wall, `@` player, `+` player on goal, `$` box, `*` box on goal, `.` goal, ` ` floor.

Eight puzzles of graduated difficulty are at `/app/puzzles/puzzle_01.xsb` through `/app/puzzles/puzzle_08.xsb`, ranging from 1 box to 6 boxes. A solution is valid if, after replaying all moves from the initial state, every box rests on a goal square. Sokoban is PSPACE-complete; naive BFS will fail on the harder puzzles without deadlock pruning and search heuristics.

Build tools available: `g++` (C++17), `cmake` (3.x), `make`.