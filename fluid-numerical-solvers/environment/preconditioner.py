"""
Preconditioners for iterative linear solvers.
"""


class NullPreconditioner:
    """Identity (no-op) preconditioner. Provided as a reference."""

    def build(self, A):
        pass

    def solve(self, r):
        return list(r)


class DiagonalPreconditioner:
    """
    Jacobi (diagonal) preconditioner.
    M = diag(A), so M^{-1}r = r / diag(A) element-wise.
    """

    def __init__(self):
        self._inv_diag = []

    def build(self, A):
        """Extract the diagonal of A and store its element-wise inverse."""
        raise NotImplementedError("Implement diagonal preconditioner build")

    def solve(self, r):
        """Apply M^{-1}: element-wise multiplication by inv_diag."""
        raise NotImplementedError("Implement diagonal preconditioner solve")


class ICPreconditioner:
    """
    Incomplete Cholesky IC(0) preconditioner for SPD sparse matrices.

    Computes an approximate Cholesky factorization A ~ LL^T where the
    lower-triangular factor L retains only the sparsity pattern of the
    lower triangle of A (zero fill-in).

    The preconditioner solve computes s = (LL^T)^{-1} r via forward
    substitution (Ly = r) followed by backward substitution (L^T s = y).
    """

    def __init__(self):
        self._n = 0
        self._L = None

    def build(self, A):
        """
        Compute the IC(0) factorization from SparseMatrix A.
        A must be symmetric positive definite.
        """
        raise NotImplementedError("Implement IC(0) factorization")

    def solve(self, r):
        """
        Solve (LL^T) s = r via forward and backward substitution.
        Returns s as a list of floats.
        """
        raise NotImplementedError("Implement IC(0) triangular solve")
