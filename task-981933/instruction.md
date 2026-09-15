Several XCSP3-core XML constraint problem instances (both CSP and COP) are provided at `/app/instances/`. MiniZinc 2.8.5 is installed at `/opt/minizinc/bin/minizinc` (on `PATH`) with bundled Chuffed and Gecode solvers.

Create `/app/compiler.py` such that running `python3 /app/compiler.py` reads every `.xml` instance in `/app/instances/`, generates an equivalent MiniZinc `.mzn` model for each in `/app/models/`, solves the model, and writes a JSON result to `/app/results/` (e.g., `magic_square.xml` produces `magic_square.mzn` and `magic_square.json`).

Result JSON format:
- Satisfiable CSP: `{"status": "SAT", "solution": {"x[0]": 1, "x[1]": 3, ...}}`
- Optimal COP: `{"status": "OPTIMUM", "objective": <int>, "solution": {...}}`
- Unsatisfiable: `{"status": "UNSAT"}`

Solution keys must use the XCSP3 variable names exactly (e.g., `"x[0]"`, `"q[3]"`, `"c[2]"`).