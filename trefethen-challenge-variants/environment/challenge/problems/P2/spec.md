# Sparse Matrix Inverse Entry

Construct an N x N sparse matrix A where:

- Diagonal entries: a_{ii} = p_i, the i-th prime number (p_1 = 2, p_2 = 3, p_3 = 5, ...)
- Off-diagonal entries: a_{ij} = 1 whenever |i - j| belongs to the offset set
- All other entries are zero

The matrix dimension N, the target entry of A^{-1} to compute, and the offset set
are specified in `offsets.txt` in this directory.
