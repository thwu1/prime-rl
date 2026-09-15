The Newton-Schulz quintic iteration applies the polynomial `phi(x) = a*x + b*x^3 + c*x^5` iteratively to normalized singular values to approximately orthogonalize matrices. After normalization, singular values lie in `(0, x_max]` and must be driven close to 1.

An evaluation framework is provided at `/opt/ns_task/ns_iteration.py`. Three optimization targets are specified in `/opt/ns_task/targets.json`:

- **uniform_steady** (epsilon=0.35, 10 iterations): Find a single `(a, b, c)` triple maximizing `a` (= phi'(0), controlling convergence speed for small singular values) such that after 10 iterations, all `x in [0.01, 1]` map to within epsilon of 1.
- **perstep_finite** (epsilon=0.35, 5 steps): Find 5 per-step coefficient triples `[(a1,b1,c1), ..., (a5,b5,c5)]` maximizing `a1` such that after exactly 5 steps, all `x in [0.01, 1/1.02]` map to within epsilon of 1.
- **uniform_tight** (epsilon=0.05, 10 iterations): Same structure as uniform_steady but with tighter tolerance, requiring the output to remain within 0.05 of 1.

Write results to `/app/results.json`. Each target key must map to an object containing `"coefficients"` (list of 3 floats for uniform, list of 5 three-element lists for per-step), `"worst_case_error"` (float), and `"slope_at_zero"` (float, equal to `a` or `a1`).