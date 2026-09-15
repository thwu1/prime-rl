# Numerical Analysis Challenge Suite

Solve the following three computational problems. Write your answers to `/app/answers.json` in this exact JSON format:

```json
{
    "problem1": <number>,
    "problem2": <integer>,
    "problem3": <number>
}
```

Each floating-point answer must be accurate to at least 10 significant digits. The integer answer must be exact.

## Problem 1: Sparse Matrix Inverse Entry

Construct the N x N matrix **A** (where N = 3,000) defined by:

- Diagonal: a_{ii} = p_i, the i-th prime number (p_1=2, p_2=3, p_3=5, p_4=7, p_5=11, ...)
- Off-diagonal: a_{ij} = 1 whenever i != j and |i - j| is in {1, 3, 9, 27, 81, 243, 729, 2187}
- All other entries are 0

Using 1-based indexing for both rows and columns, compute **(A^{-1})_{1,1}** -- the (1,1) entry of the inverse matrix (top-left corner).

## Problem 2: Tridiagonal Eigenvalue Count

Construct the N x N symmetric tridiagonal matrix **T** (where N = 10,000) defined by:

- Main diagonal: t_{ii} = 2 + 0.5 * cos(2 * pi * i / N), for i = 1, 2, ..., N
- Sub/super-diagonal: t_{i,i+1} = t_{i+1,i} = -1, for i = 1, 2, ..., N-1
- All other entries are 0

Count the exact number of eigenvalues of **T** that lie strictly inside the open interval (0.01, 0.05).

## Problem 3: Log-Determinant of Sparse Matrix

Using the same matrix **A** from Problem 1, compute:

**ln|det(A)|** -- the natural logarithm of the absolute value of the determinant of A.

This answer must be accurate to at least 10 significant digits.
