#!/usr/bin/env python3
"""
Fix all defects in the PDE benchmark pipeline:
1. Makefile: replace -c (compile-only) with -shared -fPIC for shared library
2. bindings.py: fix ctypes c_int -> c_double for nu parameter
3. stencils.c: replace first-order upwind with Lax-Wendroff scheme
4. heat_cn.py: convert backward Euler to Crank-Nicolson
5. poisson_5pt.py: fix grid spacing h=1/N -> h=1/(N+1)
6. poisson_compact.py: fix RHS with source averaging for 4th-order accuracy
"""

import textwrap


def fix_makefile():
    """Replace -c (compile-only) with -shared -fPIC for shared library."""
    content = textwrap.dedent("""\
        CC = gcc
        CFLAGS = -O2 -Wall -std=c11 -fPIC

        SRCDIR = kernels
        TARGET = libpde_kernels.so

        all: $(TARGET)

        $(TARGET): $(SRCDIR)/stencils.c
        \t$(CC) $(CFLAGS) -shared -o $@ $< -lm

        clean:
        \trm -f $(TARGET)

        .PHONY: all clean
    """)
    with open("/app/Makefile", "w") as f:
        f.write(content)


def fix_stencils_c():
    """Replace first-order upwind with actual Lax-Wendroff scheme."""
    content = textwrap.dedent("""\
        #include "stencils.h"
        #include <math.h>
        #include <stdlib.h>
        #include <string.h>

        void thomas_solve(int n, const double *a_in, const double *b_in,
                          const double *c_in, const double *d_in, double *x) {
            double *b = (double *)malloc(n * sizeof(double));
            double *d = (double *)malloc(n * sizeof(double));
            memcpy(b, b_in, n * sizeof(double));
            memcpy(d, d_in, n * sizeof(double));

            for (int i = 1; i < n; i++) {
                double m = a_in[i] / b[i - 1];
                b[i] -= m * c_in[i - 1];
                d[i] -= m * d[i - 1];
            }

            x[n - 1] = d[n - 1] / b[n - 1];
            for (int i = n - 2; i >= 0; i--) {
                x[i] = (d[i] - c_in[i] * x[i + 1]) / b[i];
            }

            free(b);
            free(d);
        }

        void lax_wendroff_step(const double *u, double *u_new, int N, double nu) {
            int i;
            for (i = 0; i < N; i++) {
                int ip = (i + 1) % N;
                int im = (i - 1 + N) % N;
                u_new[i] = u[i]
                    - 0.5 * nu * (u[ip] - u[im])
                    + 0.5 * nu * nu * (u[ip] - 2.0 * u[i] + u[im]);
            }
        }

        double compute_rms_error(const double *u_num, const double *u_exact, int n) {
            double sum_sq = 0.0;
            int i;
            for (i = 0; i < n; i++) {
                double diff = u_num[i] - u_exact[i];
                sum_sq += diff * diff;
            }
            return sqrt(sum_sq / (double)n);
        }
    """)
    with open("/app/kernels/stencils.c", "w") as f:
        f.write(content)


def fix_bindings():
    """Fix ctypes type declaration: nu should be c_double, not c_int."""
    content = textwrap.dedent('''\
        """Python ctypes bindings for the PDE kernel shared library."""
        import ctypes
        import os

        import numpy as np

        _lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libpde_kernels.so")
        _lib = ctypes.CDLL(_lib_path)

        _lib.thomas_solve.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        _lib.thomas_solve.restype = None

        _lib.lax_wendroff_step.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
            ctypes.c_double,
        ]
        _lib.lax_wendroff_step.restype = None

        _lib.compute_rms_error.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        _lib.compute_rms_error.restype = ctypes.c_double


        def thomas_solve(a, b, c, d):
            n = len(b)
            a_c = np.ascontiguousarray(a, dtype=np.float64)
            b_c = np.ascontiguousarray(b, dtype=np.float64)
            c_c = np.ascontiguousarray(c, dtype=np.float64)
            d_c = np.ascontiguousarray(d, dtype=np.float64)
            x_c = np.empty(n, dtype=np.float64)
            _lib.thomas_solve(
                n,
                a_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                b_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                c_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                d_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                x_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            )
            return x_c


        def lax_wendroff_step(u, nu):
            N = len(u)
            u_c = np.ascontiguousarray(u, dtype=np.float64)
            u_new = np.empty(N, dtype=np.float64)
            _lib.lax_wendroff_step(
                u_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                u_new.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                N,
                float(nu),
            )
            return u_new


        def rms_error(u_num, u_exact):
            n = len(u_num)
            u_n = np.ascontiguousarray(u_num, dtype=np.float64)
            u_e = np.ascontiguousarray(u_exact, dtype=np.float64)
            return _lib.compute_rms_error(
                u_n.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                u_e.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                n,
            )
    ''')
    with open("/app/bindings.py", "w") as f:
        f.write(content)


def fix_poisson_5pt():
    """Fix grid spacing: h = 1/(N+1) instead of 1/N."""
    content = textwrap.dedent("""\
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
    """)
    with open("/app/solvers/poisson_5pt.py", "w") as f:
        f.write(content)


def fix_poisson_compact():
    """Fix RHS with source averaging for 4th-order accuracy."""
    content = textwrap.dedent("""\
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
    """)
    with open("/app/solvers/poisson_compact.py", "w") as f:
        f.write(content)


def fix_heat_cn():
    """Convert backward Euler to Crank-Nicolson."""
    content = textwrap.dedent("""\
        import numpy as np

        def solve(N):
            from bindings import thomas_solve

            T_final = 0.1
            N_t = N
            h = 1.0 / (N + 1)
            dt = T_final / N_t
            r = dt / h**2

            x = np.linspace(h, 1.0 - h, N)
            u = np.sin(np.pi * x)

            # Crank-Nicolson: LHS = (I + r/2 * A), RHS = (I - r/2 * A)
            a_L = (-r / 2.0) * np.ones(N)
            b_L = (1.0 + r) * np.ones(N)
            c_L = (-r / 2.0) * np.ones(N)

            for _ in range(N_t):
                # RHS: (I - r/2 * A) @ u
                rhs = (1.0 - r) * u.copy()
                rhs[1:] += (r / 2.0) * u[:-1]
                rhs[:-1] += (r / 2.0) * u[1:]
                u = thomas_solve(a_L, b_L, c_L, rhs)

            u_exact = np.exp(-np.pi**2 * T_final) * np.sin(np.pi * x)
            return float(np.sqrt(np.mean((u - u_exact)**2)))
    """)
    with open("/app/solvers/heat_cn.py", "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_makefile()
    fix_stencils_c()
    fix_bindings()
    fix_poisson_5pt()
    fix_poisson_compact()
    fix_heat_cn()
    print("All defects fixed.")
