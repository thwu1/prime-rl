The Newton-Schulz (NS) quintic iteration approximates the polar decomposition of a matrix by repeatedly applying `phi(sigma) = a*sigma + b*sigma^3 + c*sigma^5` to each singular value of a Frobenius-normalized input. After sufficient iterations, singular values converge to 1, recovering the polar factor `U @ V.T`.

The problem specification, parameters, and output format are defined in `/app/problem_spec.py`. Solve the three optimization problems below and write results to `/app/results.json`.

## Part 1 — Implementation & Verification

Implement the NS iteration and apply it (using coefficients `(3.4445, -4.7750, 2.0315)`, 5 iterations) to orthogonalize random matrices generated per the spec. For each matrix, report the Frobenius-norm error between the NS approximation and the true SVD-based polar factor. The matrix iteration operates as `X <- a*X + (b*X*X^T + c*(X*X^T)^2) * X`, with input normalized by Frobenius norm. For tall matrices, transpose before iterating and transpose back.

## Part 2 — Fixed-Coefficient Optimization

Find quintic polynomial coefficients `(a, b, c)` satisfying `a + b + c = 1` that maximize `a` (the convergence rate for small singular values), subject to: 15 iterations of `phi` map every point in the evaluation grid to within 0.01 of 1.0, with no intermediate value exceeding the divergence bound.

## Part 3 — Per-Iteration Coefficient Optimization

Find 5 independent coefficient triples `(a_i, b_i, c_i)` that maximize `prod(a_i)`, subject to: the composed map `phi_5 o ... o phi_1` sends every grid point into `[0.65, 1.35]`, with no intermediate composition exceeding the divergence bound. No sum constraint on individual triples.

## Output Format

Write `/app/results.json` with keys `"part1"`, `"part2"`, `"part3"` containing the fields specified in `/app/problem_spec.py`.