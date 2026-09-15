#!/usr/bin/env python3
"""
Fix the four buggy PDE solvers in /app/solvers/ and run the benchmark.
"""

import textwrap


def write_fixed_poisson_5pt():
    """Fix: h = 1/(N+1) instead of 1/N for Dirichlet interior-only grid."""
    code = textwrap.dedent('''\
        import numpy as np
        from scipy import sparse
        from scipy.sparse.linalg import spsolve

        def solve(N):
            h = 1.0 / (N + 1)
            x = np.linspace(h, 1.0 - h, N)
            y = np.linspace(h, 1.0 - h, N)
            X, Y = np.meshgrid(x, y, indexing="ij")
            u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)
            f_vals = 2.0 * np.pi**2 * np.sin(np.pi * X) * np.sin(np.pi * Y)
            ones = np.ones(N)
            T = sparse.diags([-ones[:-1], 2.0 * ones, -ones[:-1]], [-1, 0, 1], format="csr")
            I_N = sparse.eye(N, format="csr")
            A = (sparse.kron(T, I_N) + sparse.kron(I_N, T)) / h**2
            u_num = spsolve(A, f_vals.ravel()).reshape((N, N))
            return float(np.sqrt(np.mean((u_num - u_exact)**2)))
    ''')
    with open("/app/solvers/poisson_5pt.py", "w") as f:
        f.write(code)


def write_fixed_poisson_compact():
    """Fix: use RHS source averaging for 4th-order accuracy."""
    code = textwrap.dedent('''\
        import numpy as np
        from scipy import sparse
        from scipy.sparse.linalg import spsolve

        def solve(N):
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

            A = (
                20.0 * sparse.kron(I_N, I_N)
                - 4.0 * (sparse.kron(S, I_N) + sparse.kron(I_N, S))
                - sparse.kron(S_p, S_p)
                - sparse.kron(S_m, S_m)
                - sparse.kron(S_p, S_m)
                - sparse.kron(S_m, S_p)
            )

            # Modified RHS with source averaging for 4th-order accuracy
            f_pad = np.zeros((N + 2, N + 2))
            f_pad[1:-1, 1:-1] = f_vals
            b_2d = (h**2 / 2.0) * (
                8.0 * f_pad[1:-1, 1:-1]
                + f_pad[:-2, 1:-1]
                + f_pad[2:, 1:-1]
                + f_pad[1:-1, :-2]
                + f_pad[1:-1, 2:]
            )

            u_num = spsolve(A.tocsr(), b_2d.ravel()).reshape((N, N))
            return float(np.sqrt(np.mean((u_num - u_exact)**2)))
    ''')
    with open("/app/solvers/poisson_compact.py", "w") as f:
        f.write(code)


def write_fixed_heat_cn():
    """Fix: Crank-Nicolson (2nd order) instead of backward Euler (1st order)."""
    code = textwrap.dedent('''\
        import numpy as np

        def solve(N):
            T_final = 0.1
            N_t = N
            h = 1.0 / (N + 1)
            dt = T_final / N_t
            r = dt / h**2

            x = np.linspace(h, 1.0 - h, N)
            u = np.sin(np.pi * x)

            # Crank-Nicolson: LHS = (I + r/2 * A), RHS = (I - r/2 * A)
            diag_L = (1.0 + r) * np.ones(N)
            off_L = (-r / 2.0) * np.ones(N - 1)
            L = np.diag(diag_L) + np.diag(off_L, -1) + np.diag(off_L, 1)

            diag_R = (1.0 - r) * np.ones(N)
            off_R = (r / 2.0) * np.ones(N - 1)
            R = np.diag(diag_R) + np.diag(off_R, -1) + np.diag(off_R, 1)

            for _ in range(N_t):
                u = np.linalg.solve(L, R @ u)

            u_exact = np.exp(-np.pi**2 * T_final) * np.sin(np.pi * x)
            return float(np.sqrt(np.mean((u - u_exact)**2)))
    ''')
    with open("/app/solvers/heat_cn.py", "w") as f:
        f.write(code)


def write_fixed_advection_lw():
    """Fix: Lax-Wendroff (2nd order) instead of first-order upwind."""
    code = textwrap.dedent('''\
        import numpy as np

        def solve(N):
            T_final = 1.0
            c = 1.0
            h = 1.0 / N
            CFL_target = 0.8
            dt = CFL_target * h / c
            N_t = int(round(T_final / dt))
            dt = T_final / N_t
            nu = c * dt / h

            x = np.linspace(0.0, 1.0 - h, N)
            u = np.sin(2.0 * np.pi * x)

            for _ in range(N_t):
                u_p = np.roll(u, -1)  # u_{i+1}
                u_m = np.roll(u, 1)   # u_{i-1}
                u = (
                    u
                    - 0.5 * nu * (u_p - u_m)
                    + 0.5 * nu**2 * (u_p - 2.0 * u + u_m)
                )

            u_exact = np.sin(2.0 * np.pi * (x - T_final))
            return float(np.sqrt(np.mean((u - u_exact)**2)))
    ''')
    with open("/app/solvers/advection_lw.py", "w") as f:
        f.write(code)


if __name__ == "__main__":
    write_fixed_poisson_5pt()
    write_fixed_poisson_compact()
    write_fixed_heat_cn()
    write_fixed_advection_lw()
    print("All solvers fixed.")
