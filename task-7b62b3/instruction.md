A researcher's workspace for exact cover experiments is at `/app/`. It contains Knuth's DLX1 solver source and several exact cover problem files. The researcher departed before finishing the work.

Audit the workspace, build a working exact cover solver, and produce these results:

- `/app/results/solution_counts.txt` — verified solution count for every `.dlx` file in `/app/problems/`. Format: one `<filename> <count>` pair per line.
- `/app/results/bug_report.txt` — one problem file has a constraint modeling error that causes incorrect results. Identify the file, explain the root cause of the encoding error, and describe the fix.
- `/app/results/corrected.dlx` — a corrected version of the buggy problem file that produces the expected result.
- `/app/results/sudoku_solution.txt` — the Sudoku puzzle solution as an 81-character digit string (row-major order, digits 1-9). The puzzle is in `/app/puzzle.txt`.
- `/app/results/unknown_analysis.txt` — determine what combinatorial problem `/app/problems/unknown.dlx` encodes by analyzing its constraint structure. Describe the problem and state the solution count.

Partial notes from the researcher are in `/app/notes.txt`.