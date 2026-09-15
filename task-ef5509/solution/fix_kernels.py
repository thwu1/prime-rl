#!/usr/bin/env python3
"""
Fix data-race bugs in five OpenMP parallel kernels.

Each kernel has a specific class of data-race bug.  This script reads the
original source, applies a targeted transformation, and writes the corrected
version back.

Uses #pragma omp parallel for (fork/join per worksharing region) so that
ThreadSanitizer correctly sees the happens-before edges at each join point.

"""

import os

SRC_DIR = "/app/src"


def fix_histogram():
    """histogram.c: race on shared histogram bins.
    Fix: add #pragma omp atomic before the increment."""
    path = os.path.join(SRC_DIR, "histogram.c")
    with open(path) as f:
        code = f.read()

    old = "        histogram[data[i]]++;"
    new = (
        "        #pragma omp atomic\n"
        "        histogram[data[i]]++;"
    )
    code = code.replace(old, new)
    with open(path, "w") as f:
        f.write(code)


def fix_jacobi2d():
    """jacobi2d.c: in-place stencil update causes read/write race on
    neighbouring rows processed by different threads.
    Fix: double-buffer with two grids; each iteration reads from one and
    writes to the other.  #pragma omp parallel for per iteration gives TSan
    a clean fork/join edge between iterations."""
    path = os.path.join(SRC_DIR, "jacobi2d.c")

    fixed = """\
/*
 * Parallel 2D Jacobi stencil iteration using OpenMP.
 * Iteratively solves a discrete Laplace equation on a 2D grid.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define GRID_SIZE 100
#define NUM_ITER 50

int main() {
    double (*buf[2])[GRID_SIZE];
    buf[0] = malloc(GRID_SIZE * sizeof(*buf[0]));
    buf[1] = malloc(GRID_SIZE * sizeof(*buf[1]));

    for (int i = 0; i < GRID_SIZE; i++)
        for (int j = 0; j < GRID_SIZE; j++) {
            double val = (i == 0 || i == GRID_SIZE - 1 ||
                          j == 0 || j == GRID_SIZE - 1) ? 1.0 : 0.0;
            buf[0][i][j] = val;
            buf[1][i][j] = val;
        }

    for (int iter = 0; iter < NUM_ITER; iter++) {
        int s = iter & 1;
        int d = 1 - s;
        #pragma omp parallel for
        for (int i = 1; i < GRID_SIZE - 1; i++) {
            for (int j = 1; j < GRID_SIZE - 1; j++) {
                buf[d][i][j] = 0.25 * (buf[s][i - 1][j] + buf[s][i + 1][j] +
                                        buf[s][i][j - 1] + buf[s][i][j + 1]);
            }
        }
    }

    int r = NUM_ITER & 1;
    double checksum = 0.0;
    for (int i = 0; i < GRID_SIZE; i++)
        for (int j = 0; j < GRID_SIZE; j++)
            checksum += buf[r][i][j];
    printf("%.10f\\n", checksum);

    free(buf[0]);
    free(buf[1]);
    return 0;
}
"""
    with open(path, "w") as f:
        f.write(fixed)


def fix_nbody():
    """nbody.c: Newton's 3rd-law optimisation writes to fx[j]/fy[j]/fz[j]
    from multiple threads concurrently.
    Fix: each thread computes the full O(N^2) force on its own particles
    using thread-local accumulators — no cross-particle writes.
    Position update runs sequentially after the parallel for join."""
    path = os.path.join(SRC_DIR, "nbody.c")

    fixed = """\
/*
 * Parallel N-body gravitational simulation using OpenMP.
 * Computes pairwise gravitational forces and updates particle positions.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <omp.h>

#define NUM_PARTICLES 200
#define NUM_STEPS 10
#define DT 0.01
#define SOFTENING 1e-9

int main() {
    double *x  = (double *)malloc(NUM_PARTICLES * sizeof(double));
    double *y  = (double *)malloc(NUM_PARTICLES * sizeof(double));
    double *z  = (double *)malloc(NUM_PARTICLES * sizeof(double));
    double *vx = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *vy = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *vz = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *mass = (double *)malloc(NUM_PARTICLES * sizeof(double));

    srand(42);
    for (int i = 0; i < NUM_PARTICLES; i++) {
        x[i] = (double)rand() / RAND_MAX;
        y[i] = (double)rand() / RAND_MAX;
        z[i] = (double)rand() / RAND_MAX;
        mass[i] = 1.0;
    }

    for (int step = 0; step < NUM_STEPS; step++) {
        /* Compute forces and update velocities — each thread owns its i */
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < NUM_PARTICLES; i++) {
            double lfx = 0.0, lfy = 0.0, lfz = 0.0;
            for (int j = 0; j < NUM_PARTICLES; j++) {
                if (i == j) continue;
                double dx = x[j] - x[i];
                double dy = y[j] - y[i];
                double dz = z[j] - z[i];
                double r = sqrt(dx * dx + dy * dy + dz * dz + SOFTENING);
                double f = mass[i] * mass[j] / (r * r * r);
                lfx += f * dx;
                lfy += f * dy;
                lfz += f * dz;
            }
            vx[i] += lfx * DT;
            vy[i] += lfy * DT;
            vz[i] += lfz * DT;
        }
        /* Position update after join — all velocities are final */
        for (int i = 0; i < NUM_PARTICLES; i++) {
            x[i] += vx[i] * DT;
            y[i] += vy[i] * DT;
            z[i] += vz[i] * DT;
        }
    }

    double ke = 0.0;
    for (int i = 0; i < NUM_PARTICLES; i++)
        ke += 0.5 * mass[i] * (vx[i]*vx[i] + vy[i]*vy[i] + vz[i]*vz[i]);
    printf("%.10f\\n", ke);

    free(x); free(y); free(z);
    free(vx); free(vy); free(vz);
    free(mass);
    return 0;
}
"""
    with open(path, "w") as f:
        f.write(fixed)


def fix_lu_factor():
    """lu_factor.c: the outer k-loop has a loop-carried dependency — each
    elimination step reads rows modified by the previous step.
    Fix: parallelize the independent i-loop (rows being eliminated) instead
    of the dependent k-loop.  #pragma omp parallel for per k-step gives TSan
    a clean fork/join edge between elimination steps."""
    path = os.path.join(SRC_DIR, "lu_factor.c")

    fixed = """\
/*
 * Parallel in-place LU factorization (no pivoting) using OpenMP.
 * Decomposes a diagonally-dominant matrix A into L and U factors
 * stored in the same matrix.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define MAT_SIZE 100

int main() {
    double *A = (double *)malloc(MAT_SIZE * MAT_SIZE * sizeof(double));

    srand(42);
    for (int i = 0; i < MAT_SIZE; i++)
        for (int j = 0; j < MAT_SIZE; j++)
            A[i * MAT_SIZE + j] = (double)(rand() % 10) + 1.0
                                  + (i == j ? MAT_SIZE * 10.0 : 0.0);

    for (int k = 0; k < MAT_SIZE - 1; k++) {
        #pragma omp parallel for
        for (int i = k + 1; i < MAT_SIZE; i++) {
            A[i * MAT_SIZE + k] /= A[k * MAT_SIZE + k];
            for (int j = k + 1; j < MAT_SIZE; j++) {
                A[i * MAT_SIZE + j] -= A[i * MAT_SIZE + k] * A[k * MAT_SIZE + j];
            }
        }
    }

    double diag_sum = 0.0, off_sum = 0.0;
    for (int i = 0; i < MAT_SIZE; i++)
        for (int j = 0; j < MAT_SIZE; j++) {
            if (i == j)
                diag_sum += A[i * MAT_SIZE + j];
            else
                off_sum += A[i * MAT_SIZE + j];
        }
    printf("%.10f\\n%.10f\\n", diag_sum, off_sum);

    free(A);
    return 0;
}
"""
    with open(path, "w") as f:
        f.write(fixed)


def fix_wavefront():
    """wavefront.c: collapse(2) on the i,j loops violates the wavefront
    dependency — cell (i,j) depends on (i-1,j), (i,j-1), (i-1,j-1).
    Fix: iterate along anti-diagonals d = i + j.  All cells on the same
    anti-diagonal are independent.  #pragma omp parallel for per diagonal
    gives TSan a clean fork/join edge between diagonals."""
    path = os.path.join(SRC_DIR, "wavefront.c")

    fixed = """\
/*
 * Parallel 2D wavefront (dynamic programming) computation using OpenMP.
 * Each cell dp[i][j] depends on dp[i-1][j], dp[i][j-1], and dp[i-1][j-1].
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define N 200

int main() {
    int *dp = (int *)calloc(N * N, sizeof(int));

    srand(42);
    for (int i = 0; i < N; i++) {
        dp[i] = rand() % 10;
        dp[i * N] = rand() % 10;
    }

    /* Process anti-diagonals: d = i + j, ranging from 2 to 2*(N-1).
       All cells on the same anti-diagonal are independent. */
    for (int d = 2; d <= 2 * (N - 1); d++) {
        int i_start = (d - N + 1 > 1) ? (d - N + 1) : 1;
        int i_end   = (d - 1 < N - 1) ? (d - 1) : (N - 1);

        #pragma omp parallel for
        for (int i = i_start; i <= i_end; i++) {
            int j = d - i;
            dp[i * N + j] = dp[(i - 1) * N + j]
                          + dp[i * N + (j - 1)]
                          + dp[(i - 1) * N + (j - 1)];
        }
    }

    long long checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += dp[i * N + j];
    printf("%lld\\n", checksum);

    free(dp);
    return 0;
}
"""
    with open(path, "w") as f:
        f.write(fixed)


if __name__ == "__main__":
    fix_histogram()
    fix_jacobi2d()
    fix_nbody()
    fix_lu_factor()
    fix_wavefront()
    print("All five kernels fixed.")
