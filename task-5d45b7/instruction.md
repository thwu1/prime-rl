Three optimization problems from the CUTEst test collection are provided as `.SIF` files in `/app/problems/`. The SIF (Standard Input Format) is the native problem encoding used by CUTEst — each file fully specifies a nonlinear optimization problem including its variables, objective function, constraints, variable bounds, and starting point. One of the three problems is a custom problem not found in any public CUTEst distribution.

Write a Python program in `/app/` that:

- Reads and interprets each `.SIF` file to recover the mathematical optimization problem it encodes
- Finds the minimum of each problem, respecting any constraints and variable bounds
- Writes results to `/app/results.json` in the following format:

```json
{
  "problems": [
    {
      "name": "PROBNAME",
      "optimal_value": 0.0,
      "solution": [1.0, 1.0],
      "n_vars": 2,
      "n_constraints": 0
    }
  ]
}
```

The `name` field must match the `NAME` declared in each SIF file. The `n_constraints` field counts general constraints (inequality and equality), not variable bounds. The `solution` array must contain the variable values at the optimum.

All code should reside in `/app/`.