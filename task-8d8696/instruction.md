The Muon optimizer orthogonalizes weight update matrices via a Newton-Schulz (NS) iteration that repeatedly applies a polynomial to singular values (normalized to [0,1] by Frobenius norm). The quintic variant uses phi(x) = ax + bx^3 + cx^5. The coefficient a = phi'(0) controls convergence speed for small singular values, but excessively large a causes overshoot.

A starter module at `/app/ns_analysis.py` provides the NS iteration functions, an evaluation grid `EVAL_GRID = np.linspace(0.01, 1.0, 50000)`, a deterministic test matrix generator, and the expected JSON output format.

Produce `/app/results.json` containing:

**Quintic coefficients**: Find (a, b, c) maximizing a subject to max_{x in EVAL_GRID} |phi^5(x) - 1| <= 0.30. Report a, b, c, and `convergence_profile` -- a list of 20 floats giving max_{x in EVAL_GRID} |phi^k(x) - 1| for k=1,...,20.

**Septic coefficients**: For phi(x) = ax + bx^3 + cx^5 + dx^7, find (a, b, c, d) maximizing a subject to the same constraint (N=5, epsilon=0.30). Report a, b, c, d.

**Fixed-point analysis**: Using the quintic coefficients, find all non-negative real fixed points x* of phi (where phi(x*) = x*), including x=0. For each, compute phi'(x*). Report as a sorted list of {"x": ..., "phi_prime": ...} objects.

**Matrix orthogonalization**: Apply `ns_orthogonalize_matrix(G, a, b, c, n_iters=5)` from the starter module to `generate_test_matrix(seed=42)` using the quintic coefficients. Report `frobenius_error` (||X^T X - I||_F for the 64x48 result) and `max_sv_deviation` (max|sigma_i(X) - 1|).