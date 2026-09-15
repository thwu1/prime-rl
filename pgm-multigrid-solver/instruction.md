A computational pipeline at `/app/` solves sparse symmetric positive-definite linear systems arising from 2D diffusion simulations. The current solver (`/app/baseline_solver.py`) fails to meet convergence targets on several test configurations. Baseline performance logs are in `/app/baseline_results/`.

Investigate the pipeline: examine the test matrices in `/app/data/` (`iso_32.mtx`, `aniso_32.mtx`, `iso_64.mtx`), the matrix generator (`/app/generate_matrix.py`), the baseline solver, and its logged results. Determine what causes the baseline's poor convergence and why its performance degrades across different problem configurations.

Implement a replacement solver at `/app/amg_solver.py` that satisfies all of the following requirements.

## CLI interface

```
python3 /app/amg_solver.py --matrix <path.mtx> --tol <float> --output <path.json>
```

RHS vector: b = [1,1,...,1]^T. Initial guess: x_0 = 0.

## Output JSON schema

```json
{
  "iterations": <int>,
  "residual_norm": <float>,
  "relative_residual": <float>,
  "converged": <bool>,
  "grid_complexity": <float>,
  "operator_complexity": <float>,
  "n_levels": <int>,
  "level_sizes": [<int>, ...]
}
```

- `grid_complexity` = (total unknowns summed across all solver levels) / (unknowns at the finest level).
- `operator_complexity` = (total matrix nonzeros summed across all levels) / (nonzeros at the finest level).
- `level_sizes` = list of unknowns at each level, finest to coarsest; must have at least 2 entries.

## Convergence requirements

The solver must report `converged` = true with `relative_residual` < tol (tol = 1e-8) on every test matrix, within these iteration budgets:

| Matrix | Max iterations |
|---|---|
| `iso_32.mtx` | 30 |
| `aniso_32.mtx` | 100 |
| `iso_64.mtx` | 35 |

Mesh-independent convergence: the iteration count difference between `iso_64.mtx` and `iso_32.mtx` must not exceed 15.

## Solver structure requirements

- `n_levels` >= 3 for systems with 1024 or more unknowns.
- `level_sizes` must be strictly decreasing.
- `grid_complexity` must be in [1.3, 4.0].
- `operator_complexity` must be in [1.0, 10.0].