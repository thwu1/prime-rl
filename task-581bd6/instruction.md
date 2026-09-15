Problem specifications are in `/app/spec.json`. Five singularly perturbed boundary value problems from the Cash-Mazzia-Wright numerical test set must be solved at three values of the perturbation parameter epsilon: 0.1, 0.01, and 0.001.

Each problem is a second-order ODE of the form `eps * z'' = f(t, z, z')` on a specified domain with given boundary conditions. Some boundary conditions depend on `eps` and require numerically stable evaluation (e.g., `ln(cosh(x))` for large arguments). The problems include linear and nonlinear ODEs with boundary layers, turning points, and corner layers that become increasingly sharp as epsilon decreases.

Create `/app/solve_all.py` that solves all 15 instances (5 problems x 3 epsilon values) and writes `/app/results.json` with this structure:

```json
{
  "<problem_id>": {
    "<eps>": {
      "t": [1000 uniformly spaced points on the domain],
      "y": [z(t) evaluated at those points]
    }
  }
}
```

Epsilon keys must be strings (`"0.1"`, `"0.01"`, `"0.001"`). Each `t` array must contain exactly 1000 points spanning the problem domain. Each `y` array contains the first component (z) of the numerical solution.

Solutions are verified against reference solutions with maximum pointwise error thresholds: 1e-4 at eps=0.1, 1e-3 at eps=0.01, and 1e-2 at eps=0.001.