Feature matrix `X` (n x d) and target vector `y` (n) are stored at `/app/data/X.npy` and `/app/data/y.npy`. Parameters are in `/app/data/config.json` (kernel bandwidth sigma, regularization lambda, convergence criteria, landmark count bounds).

Solve the kernel ridge regression system `(K + lambda * I) alpha = y` where K is the Gaussian RBF kernel matrix `K_ij = exp(-||x_i - x_j||^2 / (2 * sigma^2))`. The data has unbalanced cluster structure with highly non-uniform ridge leverage scores; naive uniform landmark selection will yield a poor preconditioner that fails to converge within the iteration budget.

Implement a complete Nystrom-preconditioned conjugate gradient pipeline:

- **Ridge leverage score estimation** via a randomized pilot Nystrom sketch, used to weight landmark sampling so that under-represented data regions are adequately covered.
- **Nystrom preconditioner** assembled from the selected landmarks and applied efficiently (O(n*s) per solve, not O(n^2)) using the Woodbury matrix identity on the low-rank kernel approximation.
- **Preconditioned CG** solving the full kernel system, converging within the iteration budget to the specified residual tolerance. Kernel matrix-vector products must be computed without forming the full n x n matrix (use chunked computation with the efficient squared-distance identity `||a-b||^2 = ||a||^2 + ||b||^2 - 2 a^T b`).

Write to `/app/output/`:

- `alpha.npy` -- solution vector alpha, shape `(n,)`
- `landmarks.npy` -- integer array of selected landmark indices
- `residual_history.npy` -- relative residual `||r_k|| / ||y||` at each iteration including initial, shape `(num_iterations + 1,)`
- `num_iterations.txt` -- single integer: CG iterations performed