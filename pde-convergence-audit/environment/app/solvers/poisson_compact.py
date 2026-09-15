"""
Solver for the 2D Poisson equation: -nabla^2 u = f on (0,1)^2 with u=0 on boundary.

Manufactured solution: u*(x,y) = sin(pi*x)*sin(pi*y)
Source term: f(x,y) = 2*pi^2*sin(pi*x)*sin(pi*y)

Uses a compact 9-point stencil for higher-order accuracy. The stencil weights
for the operator are: center=20, axial neighbors=-4 each, diagonal neighbors=-1
each, all scaled by 1/(6h^2).
"""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve


def solve(N):
    """Solve at resolution N and return the L2 (RMS) error."""
    h = 1.0 / (N + 1)
    x = np.linspace(h, 1.0 - h, N)
    y = np.linspace(h, 1.0 - h, N)
    X, Y = np.meshgrid(x, y, indexing="ij")

    u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)
    f_vals = 2.0 * np.pi**2 * np.sin(np.pi * X) * np.sin(np.pi * Y)

    I_N = sparse.eye(N, format="csr")
    S_p = sparse.diags([np.ones(N - 1)], [1], shape=(N, N), format="csr")
    S_m = sparse.diags([np.ones(N - 1)], [-1], shape=(N, N), format="csr")
    S = S_p + S_m

    # 9-point compact stencil: 20*center - 4*axial - 1*diagonal
    A = (
        20.0 * sparse.kron(I_N, I_N)
        - 4.0 * (sparse.kron(S, I_N) + sparse.kron(I_N, S))
        - sparse.kron(S_p, S_p)
        - sparse.kron(S_m, S_m)
        - sparse.kron(S_p, S_m)
        - sparse.kron(S_m, S_p)
    )

    # Right-hand side scaled by 6h^2 to match stencil normalization
    b = 6.0 * h**2 * f_vals.ravel()

    u_num = spsolve(A.tocsr(), b).reshape((N, N))
    return float(np.sqrt(np.mean((u_num - u_exact) ** 2)))
