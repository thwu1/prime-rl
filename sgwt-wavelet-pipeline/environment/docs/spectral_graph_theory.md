# Spectral Graph Theory — Reference Notes

## Graph Laplacian

Given an undirected weighted graph with adjacency matrix **W** (where
W_{ij} = w_{ij} is the edge weight between vertices i and j), the
**combinatorial graph Laplacian** is defined as:

    L = D - W

where **D** is the diagonal **degree matrix** with entries:

    D_{ii} = sum_j  W_{ij}

## Eigendecomposition

The Laplacian is real symmetric positive semi-definite, so it admits
an eigendecomposition

    L = U  Lambda  U^T

with real non-negative eigenvalues  0 = lambda_1 <= lambda_2 <= ... <= lambda_N
and an orthonormal eigenvector matrix U.  For a connected graph the
multiplicity of the zero eigenvalue is exactly one.

The eigenvalues of the combinatorial Laplacian are non-negative and
their upper bound depends on the graph's topology and edge weights.
The normalized Laplacian L_norm = D^{-1/2} L D^{-1/2} has its
spectrum confined to [0, 2], but this pipeline operates on the
combinatorial (unnormalized) form whose eigenvalues are unbounded
above.

The eigenvectors form the **graph Fourier basis**, and the
eigenvalues can be interpreted as frequencies.

## Graph Fourier Transform

For a signal  f  on the vertices of the graph:

    f_hat = U^T f          (analysis — project onto eigenbasis)
    f     = U   f_hat      (synthesis — reconstruct)

Spectral filtering applies a diagonal operator in the Fourier domain:

    g(L) f  =  U  diag(g(lambda))  U^T  f

where  g  is a **kernel function** evaluated at each eigenvalue.
