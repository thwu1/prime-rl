Solve three numerical analysis problems to high accuracy. Each answer must be correct to at least 10 significant digits. Write all results to `/app/answers.json`.

## Problem 1: Oscillatory Improper Integral

Compute:

    I = lim_{ε→0+} ∫_ε^1 (1/x) · cos((ln x) / x) dx

The integrand has an oscillatory singularity at x = 0 whose frequency increases without bound.

## Problem 2: Sparse Matrix Inverse Entry

Construct the N×N matrix A (N = 20000) defined by:
- Diagonal entries: a_{ii} = the i-th prime number (a_{1,1}=2, a_{2,2}=3, a_{3,3}=5, …, a_{20000,20000}=224737)
- Off-diagonal entries: a_{ij} = 1 whenever |i−j| ∈ {1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384}
- All remaining entries: 0

Compute the entry in the first row and first column of A⁻¹.

## Problem 3: Brownian Exit Probability

A particle undergoing standard two-dimensional Brownian motion starts at the center of a rectangle with dimensions 10 (length) × 1 (width). It diffuses until first hitting the boundary. Compute the probability that it exits through one of the two short sides (the sides of length 1) rather than through one of the two long sides (the sides of length 10).

## Output

Write `/app/answers.json`:
```json
{
  "problem1": <float>,
  "problem2": <float>,
  "problem3": <float>
}
```

All values must be correct to at least 10 significant digits.