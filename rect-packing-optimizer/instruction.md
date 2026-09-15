A 10000x10000 grid is used to place advertisements for N companies. Each company i has a desired point (x_i, y_i) and a desired area r_i. You must place N non-overlapping, axis-aligned rectangles with integer coordinates and positive area such that total satisfaction is maximized.

The full problem specification, scoring formula, and input/output format are at `/app/problem.md`.

Implement a high-performance optimization solver in **C++** at `/app/solver.cpp`. The provided Makefile at `/app/Makefile` compiles it to the binary `/app/solver` using `g++ -std=c++17 -O2`. A starter template demonstrating the I/O format is at `/app/solver_template.cpp`.

Your compiled solver must achieve an **average score >= 400,000,000** across the five test cases in `/app/testcases/`.

**Build and evaluate toolchain:**

- `make -C /app` compiles `/app/solver.cpp` into the binary `/app/solver`
- `bash /app/evaluate.sh` builds the solver, runs all test cases, stores per-case results in the SQLite database at `/app/results.db`, and outputs structured JSON to stdout
- Pipe evaluation output through `jq` for inspection: `bash /app/evaluate.sh | jq '.cases[] | {case, score}'`
- Query cumulative results from the database: `sqlite3 /app/results.db "SELECT * FROM summary;"`
- Query per-case breakdown: `sqlite3 /app/results.db "SELECT case_name, score, solver_time_ms FROM results ORDER BY case_name;"`
- Score a single solution manually: `python3 /app/scorer.py <input_file> <output_file>`
- Each solver invocation must complete within 60 seconds