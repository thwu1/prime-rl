A constrained optimization framework at `/opt/optframework/` provides five problems (2D to 5D) with nonlinear inequality constraints, strict evaluation budgets, and a black-box function interface.

## Optimizer

Implement the `optimize()` function in `/app/optimizer.py`. The function signature:

```python
def optimize(f, g, c, x0, n, count, prob):
```

Arguments:
- `f(x)` — objective function (costs 1 evaluation)
- `g(x)` — gradient of f (costs 2 evaluations)
- `c(x)` — constraint vector, feasible when all components ≤ 0 (costs 1 evaluation)
- `x0` — initial point (numpy array)
- `n` — total evaluation budget (sum of all f/g/c calls must not exceed this)
- `count()` — returns current evaluation count
- `prob` — problem identifier string (`"prob1"` through `"prob5"`)

No constraint gradient is provided. Only `numpy` may be used as an external dependency. The function must return a numpy array of the same dimension as `x0`.

The optimizer is evaluated across 500 random starting points per problem. Requirements:

- **Budget compliance**: evaluation count must never exceed `n` on any seed for any problem.
- **Feasibility**: at least 475 out of 500 seeds must return feasible points (all constraint components ≤ 1e-4) for every problem.
- **Objective quality**: mean objective value across finite-valued seeds must be at or below these thresholds:
  - `prob1` ≤ 0.5
  - `prob2` ≤ 10.0
  - `prob3` ≤ 1.0
  - `prob4` ≤ 5.0
  - `prob5` ≤ 25.0

See `/opt/optframework/framework.py` for the base class API, `/opt/optframework/problems.py` for problem definitions.

## Benchmark Pipeline

After implementing the optimizer, build a benchmark pipeline using `make`, `sqlite3`, and `jq`.

Create `/app/Makefile` with the following targets:

**`benchmark`**: Run `/opt/optframework/run_test.py --csv` to produce CSV output (see `--help` for format), then import the results into a SQLite database at `/app/results.db`. The database must contain a table named `benchmark` with these columns:

| Column             | Type    |
|--------------------|---------|
| `problem`          | TEXT    |
| `seeds_total`      | INTEGER |
| `seeds_feasible`   | INTEGER |
| `mean_objective`   | REAL    |
| `budget_violations` | INTEGER |

The table must have exactly 5 rows (one per problem).

**`report`**: Query `/app/results.db` using `sqlite3` and transform the output with `jq` to produce `/app/report.json` with this structure:

```json
{
  "problems": [
    {
      "name": "<problem id>",
      "feasibility_rate": <seeds_feasible / seeds_total as float>,
      "mean_objective": <float>,
      "budget_violations": <integer>,
      "pass": <boolean: true iff feasibility_rate >= 0.95 AND mean_objective <= threshold AND budget_violations == 0>
    }
  ],
  "overall_pass": <boolean: true iff all problems pass>
}
```

The `problems` array must contain all 5 problems. Thresholds for the `pass` field are the same as the objective quality thresholds listed above.

**`all`**: Run both `benchmark` and `report` in sequence.

Run `make all` from `/app/` to generate both `/app/results.db` and `/app/report.json`.

You can test the optimizer interactively via `cd /app && python3 /opt/optframework/run_test.py`.