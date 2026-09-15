# Fibonacci-Banded Sparse Matrix Inverse

Construct a sparse square matrix M according to the specification in the data file referenced by the challenge configuration.

The matrix has a structured sparsity pattern: primes on the diagonal and unit entries at offsets determined by Fibonacci numbers. Compute a specific entry of the matrix inverse.

Equivalently, you may solve a linear system M*x = e_k (where e_k is a standard basis vector) and extract the appropriate component.

## Output Format

Write a single value to the output file specified in challenge.json, in plain decimal or scientific notation.
