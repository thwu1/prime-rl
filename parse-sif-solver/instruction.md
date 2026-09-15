The directory `/app/problems/` contains optimization problem files in the Standard Input Format (SIF), used by the CUTEst numerical optimization testing environment. Each `.SIF` file encodes a complete nonlinear optimization problem — objective function, constraints, variable bounds, and starting point — using a structured, column-oriented text format with multiple sections.

Produce `/app/solve.py` that reads every `.SIF` file from `/app/problems/`, determines the optimization problem each one encodes, finds its optimal solution, and writes all results to `/app/results.json`.

`/app/results.json` must be a JSON object keyed by problem name (as declared within the SIF file). Each entry must contain:
- `"optimal_value"`: the minimum objective function value found (float)
- `"optimal_point"`: the minimizer x* (array of floats)

The solver must be general-purpose — it must correctly handle any valid SIF problem using the same feature set as the provided files, not just the specific instances given. The provided problems span unconstrained, bound-constrained, and nonlinearly constrained optimization.