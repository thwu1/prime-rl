"""
Newton-Schulz Quintic Iteration Coefficient Optimization
=========================================================


The Newton-Schulz (NS) quintic iteration orthogonalizes a matrix by
repeatedly applying the polynomial:

    phi(sigma) = a * sigma + b * sigma^3 + c * sigma^5

to each singular value sigma of the (Frobenius-normalized) input matrix.
After sufficient iterations, singular values converge toward 1, recovering
the polar factor U @ V.T from the SVD G = U @ S @ V.T.

Problem 1: Implementation & Verification
-----------------------------------------
Implement the NS iteration and apply it to orthogonalize matrices.

- Use the Muon optimizer coefficients: (a, b, c) = (3.4445, -4.7750, 2.0315)
- Run 5 NS iteration steps
- Generate test matrices using numpy with seed MATRIX_SEED and shapes MATRIX_SHAPES
  (use np.random.default_rng(MATRIX_SEED).standard_normal(shape) for each shape in order)
- For each matrix G:
    1. Compute normalized G_hat = G / frobenius_norm(G)
    2. Apply 5 NS iterations to get approximate polar factor X
    3. Compute true polar factor P = U @ V.T via SVD of G (NOT G_hat)
    4. Report frobenius_norm(X - P)
- Report the list of 5 errors

Problem 2: Fixed-Coefficient Optimization (Exact Convergence)
-------------------------------------------------------------
Find (a, b, c) that MAXIMIZES 'a' subject to:
- a + b + c = 1    (ensures phi(1) = 1, i.e., 1 is a fixed point)
- For every x in P2_GRID: |phi^{P2_N_ITERS}(x) - 1| < P2_TOLERANCE
- For every x in P2_GRID and every k <= P2_N_ITERS: |phi^k(x)| < P2_DIVERGENCE_BOUND

Report: {"coefficients": [a, b, c], "max_error": <float>, "a_value": <float>}

Problem 3: Per-Iteration Coefficient Optimization
--------------------------------------------------
Find 5 coefficient triples [(a1,b1,c1), ..., (a5,b5,c5)] that MAXIMIZE
the product prod(a_i) subject to:
- For every x in P3_GRID: P3_LOWER_BOUND <= psi(x) <= P3_UPPER_BOUND
  where psi = phi_5 o phi_4 o ... o phi_1  (composition of 5 different quintics)
- For every x in P3_GRID and every partial composition k=1..5:
  |psi_k(x)| < P3_DIVERGENCE_BOUND
- No constraints on individual sums a_i + b_i + c_i

Report: {"coefficients": [[a1,b1,c1], ..., [a5,b5,c5]],
         "product_of_slopes": <float>, "max_error": <float>}

Output Format
-------------
Write a JSON file to OUTPUT_FILE with keys "part1", "part2", "part3".
See the parameter definitions below for exact constraints.
"""

# ============================================================
# Problem parameters
# ============================================================

# Part 1: Muon coefficients and matrix specs
MUON_COEFFS = (3.4445, -4.7750, 2.0315)
MUON_N_ITERS = 5
MATRIX_SEED = 42
MATRIX_SHAPES = [(8, 6), (16, 16), (32, 16), (64, 64), (128, 64)]

# Part 2: Fixed-coefficient optimization
P2_GRID_START = 0.01
P2_GRID_END = 1.0
P2_GRID_SIZE = 500
P2_N_ITERS = 15
P2_TOLERANCE = 0.01
P2_DIVERGENCE_BOUND = 10.0

# Part 3: Per-iteration coefficient optimization
P3_GRID_START = 0.01
P3_GRID_END = 0.98
P3_GRID_SIZE = 500
P3_N_COMPOSITIONS = 5
P3_LOWER_BOUND = 0.65
P3_UPPER_BOUND = 1.35
P3_DIVERGENCE_BOUND = 10.0

# Output path
OUTPUT_FILE = "/app/results.json"
