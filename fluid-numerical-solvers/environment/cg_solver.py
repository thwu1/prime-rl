"""
Conjugate Gradient and Preconditioned Conjugate Gradient solvers
for symmetric positive definite (SPD) linear systems Ax = b.
"""


def cg(A, b, x0, max_iter, tolerance):
    """
    Solve Ax = b using the Conjugate Gradient method.

    The matrix A must be symmetric positive definite. A must support
    A.matvec(x) which returns the matrix-vector product as a list.

    When max_iter is 0, the function should return immediately with the
    initial residual computed from x0 (without performing any iterations).

    Args:
        A: matrix object with a .matvec(x) -> list method
        b: list[float], right-hand side vector
        x0: list[float], initial guess
        max_iter: int, maximum number of iterations (may be 0)
        tolerance: float, convergence threshold on the L2 residual norm

    Returns:
        tuple (x, iterations, residual_norm):
            x: list[float], approximate solution
            iterations: int, number of iterations actually performed
            residual_norm: float, L2 norm of the final residual vector
    """
    raise NotImplementedError("Implement the Conjugate Gradient algorithm")


def pcg(A, b, x0, max_iter, tolerance, preconditioner):
    """
    Solve Ax = b using the Preconditioned Conjugate Gradient method.

    The preconditioner approximates A^{-1} and must support
    preconditioner.solve(r) returning the preconditioned residual vector.

    Args:
        A: matrix object with a .matvec(x) -> list method
        b: list[float], right-hand side vector
        x0: list[float], initial guess
        max_iter: int, maximum number of iterations
        tolerance: float, convergence threshold on the L2 residual norm
        preconditioner: object with a .solve(r) -> list method

    Returns:
        tuple (x, iterations, residual_norm):
            x: list[float], approximate solution
            iterations: int, number of iterations actually performed
            residual_norm: float, L2 norm of the final residual vector
    """
    raise NotImplementedError("Implement the Preconditioned CG algorithm")
