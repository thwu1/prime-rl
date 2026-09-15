A problem specification at `/app/problems.json` defines five singularly perturbed boundary value problems. Each is a second-order ODE of the form `eps * z'' = f(t, z, z')` rewritten as a first-order system `y1' = y2, y2' = g(t, y1, y2, eps)`. Each problem must be solved for epsilon values from 0.1 down to 0.0001.

For small epsilon, these problems develop sharp boundary layers, corner layers, or shock layers that cause standard BVP solvers to fail without proper initialization. Your solver must use parameter continuation in epsilon — solve at a larger epsilon first, then use that converged solution as the initial guess for the next smaller epsilon value.

Write `/app/solver.py` that reads `/app/problems.json`, solves all five problems for all listed epsilon values, and writes results to `/app/results.json`.

The output JSON must have this structure:

```json
{
  "problem_name": {
    "epsilon_as_string": {
      "t": [201 evenly-spaced floats on the problem domain],
      "y": [201 floats — the solution y1(t) evaluated at those points]
    }
  }
}
```

All five problems must have solutions for all four epsilon values. Note that two problems have epsilon-dependent boundary conditions expressed as formulas in the spec — these must be evaluated numerically (watch for overflow in `cosh` for small epsilon). Solutions will be verified against reference computations and ODE residual checks.