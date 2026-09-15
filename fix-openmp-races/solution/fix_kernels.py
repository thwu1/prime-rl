#!/usr/bin/env python3
"""Fix concurrency defects in OpenMP parallel kernels by writing the
corrected versions of each C source file, then compile and verify
against sequential reference implementations.

Each kernel is written from scratch rather than patched, making the
fix independent of the original file's presence or formatting.
"""

import subprocess
import sys
import os

# ---------------------------------------------------------------------------
# Fixed source code for each kernel
# ---------------------------------------------------------------------------

HISTOGRAM_FIXED = r'''/* Parallel histogram computation using OpenMP */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>

#define N 500000
#define NBINS 64

static unsigned int _lcg_state = 42;
static int lcg_rand(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (_lcg_state >> 16) & 0x7fff;
}

void compute_histogram(const int *data, int n, int *hist, int nbins) {
    memset(hist, 0, nbins * sizeof(int));
    int local_hist[NBINS];

    #pragma omp parallel private(local_hist)
    {
        memset(local_hist, 0, nbins * sizeof(int));

        #pragma omp for nowait
        for (int i = 0; i < n; i++) {
            local_hist[data[i] % nbins]++;
        }

        /* Merge local histograms into global histogram -- critical section
           prevents concurrent writes to hist[] from different threads. */
        #pragma omp critical
        {
            for (int i = 0; i < nbins; i++) {
                hist[i] += local_hist[i];
            }
        }
    }
}

int main(void) {
    int *data = (int *)malloc(N * sizeof(int));
    int hist[NBINS];

    for (int i = 0; i < N; i++) {
        data[i] = lcg_rand();
    }

    omp_set_num_threads(4);
    compute_histogram(data, N, hist, NBINS);

    long total = 0;
    for (int i = 0; i < NBINS; i++) {
        total += hist[i];
    }

    printf("total=%ld\n", total);
    printf("hist[0]=%d\n", hist[0]);
    printf("hist[31]=%d\n", hist[31]);
    printf("hist[63]=%d\n", hist[63]);

    free(data);
    return 0;
}
'''

JACOBI_FIXED = r'''/* Jacobi iterative relaxation on a 2D grid using OpenMP */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <omp.h>

#define GRID_SIZE 200
#define MAX_ITER 100

static double grid[GRID_SIZE][GRID_SIZE];
static double grid_new[GRID_SIZE][GRID_SIZE];

void init_grid(void) {
    for (int i = 0; i < GRID_SIZE; i++) {
        for (int j = 0; j < GRID_SIZE; j++) {
            if (i == 0)
                grid[i][j] = 100.0 * sin(M_PI * j / (GRID_SIZE - 1));
            else if (i == GRID_SIZE - 1)
                grid[i][j] = 100.0 * sin(M_PI * j / (GRID_SIZE - 1)) * exp(-M_PI);
            else
                grid[i][j] = 0.0;
        }
    }
}

double jacobi_step(void) {
    double max_diff = 0.0;

    /* Read from grid, write to grid_new (double buffering) */
    #pragma omp parallel for reduction(max:max_diff) collapse(2)
    for (int i = 1; i < GRID_SIZE - 1; i++) {
        for (int j = 1; j < GRID_SIZE - 1; j++) {
            grid_new[i][j] = 0.25 * (grid[i-1][j] + grid[i+1][j] +
                                      grid[i][j-1] + grid[i][j+1]);
            double diff = fabs(grid_new[i][j] - grid[i][j]);
            if (diff > max_diff) max_diff = diff;
        }
    }

    /* Copy new values back to grid (sequential -- barrier from
       parallel for ensures all threads finished above) */
    for (int i = 1; i < GRID_SIZE - 1; i++) {
        for (int j = 1; j < GRID_SIZE - 1; j++) {
            grid[i][j] = grid_new[i][j];
        }
    }

    return max_diff;
}

int main(void) {
    init_grid();
    omp_set_num_threads(4);

    int iter;
    double diff = 0.0;
    for (iter = 0; iter < MAX_ITER; iter++) {
        diff = jacobi_step();
    }

    double checksum = 0.0;
    for (int i = 0; i < GRID_SIZE; i++) {
        for (int j = 0; j < GRID_SIZE; j++) {
            checksum += grid[i][j];
        }
    }

    printf("iterations=%d\n", iter);
    printf("final_diff=%.10e\n", diff);
    printf("checksum=%.6f\n", checksum);

    return 0;
}
'''

NBODY_FIXED = r'''/* N-body gravitational force computation using OpenMP */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <omp.h>

#define NBODIES 500
#define SOFTENING 1e-9

static unsigned int _lcg_state = 12345;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
}

typedef struct {
    double x, y, z;
    double mass;
} Body;

void compute_forces(Body *bodies, int n, double *fx, double *fy, double *fz) {
    memset(fx, 0, n * sizeof(double));
    memset(fy, 0, n * sizeof(double));
    memset(fz, 0, n * sizeof(double));

    /* All-pairs: each thread only writes to its own i's forces */
    #pragma omp parallel for schedule(dynamic, 16)
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            if (i == j) continue;
            double dx = bodies[j].x - bodies[i].x;
            double dy = bodies[j].y - bodies[i].y;
            double dz = bodies[j].z - bodies[i].z;
            double dist_sq = dx*dx + dy*dy + dz*dz + SOFTENING;
            double inv_dist = 1.0 / sqrt(dist_sq);
            double inv_dist3 = inv_dist * inv_dist * inv_dist;
            double f = bodies[i].mass * bodies[j].mass * inv_dist3;

            fx[i] += f * dx;
            fy[i] += f * dy;
            fz[i] += f * dz;
        }
    }
}

int main(void) {
    Body *bodies = (Body *)malloc(NBODIES * sizeof(Body));
    double *fx = (double *)calloc(NBODIES, sizeof(double));
    double *fy = (double *)calloc(NBODIES, sizeof(double));
    double *fz = (double *)calloc(NBODIES, sizeof(double));

    for (int i = 0; i < NBODIES; i++) {
        bodies[i].x = lcg_rand_double() * 100.0;
        bodies[i].y = lcg_rand_double() * 100.0;
        bodies[i].z = lcg_rand_double() * 100.0;
        bodies[i].mass = lcg_rand_double() * 10.0 + 1.0;
    }

    omp_set_num_threads(4);
    compute_forces(bodies, NBODIES, fx, fy, fz);

    double sum_fx = 0, sum_fy = 0, sum_fz = 0;
    for (int i = 0; i < NBODIES; i++) {
        sum_fx += fx[i];
        sum_fy += fy[i];
        sum_fz += fz[i];
    }

    printf("sum_fx=%.10e\n", sum_fx);
    printf("sum_fy=%.10e\n", sum_fy);
    printf("sum_fz=%.10e\n", sum_fz);
    printf("fx[0]=%.10e\n", fx[0]);
    printf("fy[100]=%.10e\n", fy[100]);
    printf("fz[499]=%.10e\n", fz[NBODIES-1]);

    free(bodies);
    free(fx);
    free(fy);
    free(fz);
    return 0;
}
'''

CONVOLVE_FIXED = r'''/* Parallel 1D convolution using OpenMP */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <omp.h>

#define SIGNAL_LEN 200000
#define FILTER_LEN 127

static unsigned int _lcg_state = 31415;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
}

void convolve(double *signal, int n, double *filter, int m, double *output) {
    /* Parallelize over output indices: each output[i] is computed
       independently with no shared writes, eliminating the data race
       that existed when the loop was over filter coefficients (k). */
    #pragma omp parallel for
    for (int i = 0; i < n; i++) {
        double sum = 0.0;
        int k_max = (i < m - 1) ? i : m - 1;
        for (int k = 0; k <= k_max; k++) {
            sum += filter[k] * signal[i - k];
        }
        output[i] = sum;
    }
}

int main(void) {
    double *signal = (double *)malloc(SIGNAL_LEN * sizeof(double));
    double *filter = (double *)malloc(FILTER_LEN * sizeof(double));
    double *output = (double *)malloc(SIGNAL_LEN * sizeof(double));

    for (int i = 0; i < SIGNAL_LEN; i++) {
        signal[i] = lcg_rand_double() * 2.0 - 1.0;
    }
    for (int k = 0; k < FILTER_LEN; k++) {
        filter[k] = lcg_rand_double() * 0.1;
    }

    omp_set_num_threads(4);
    convolve(signal, SIGNAL_LEN, filter, FILTER_LEN, output);

    printf("output[0]=%.10e\n", output[0]);
    printf("output[63]=%.10e\n", output[63]);
    printf("output[100000]=%.10e\n", output[100000]);
    printf("output[199999]=%.10e\n", output[SIGNAL_LEN - 1]);

    double checksum = 0.0;
    for (int i = 0; i < SIGNAL_LEN; i++) checksum += output[i];
    printf("checksum=%.10e\n", checksum);

    free(signal);
    free(filter);
    free(output);
    return 0;
}
'''

PREFIX_SCAN_FIXED = r'''/* Parallel inclusive prefix sum using OpenMP */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <omp.h>

#define N 100000

static unsigned int _lcg_state = 54321;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
}

void parallel_prefix_sum(double *data, int n) {
    int nthreads;
    double *chunk_totals;

    #pragma omp parallel
    {
        int tid = omp_get_thread_num();

        #pragma omp single
        {
            nthreads = omp_get_num_threads();
            chunk_totals = (double *)calloc(nthreads, sizeof(double));
        }
        /* implicit barrier after single */

        int chunk_size = (n + nthreads - 1) / nthreads;
        int start = tid * chunk_size;
        int end = start + chunk_size;
        if (end > n) end = n;

        /* Phase 1: local prefix sum within each chunk */
        for (int i = start + 1; i < end; i++) {
            data[i] += data[i - 1];
        }

        if (end > start)
            chunk_totals[tid] = data[end - 1];

        #pragma omp barrier

        /* Phase 2: prefix sum of chunk totals (single thread) */
        #pragma omp single
        for (int i = 1; i < nthreads; i++) {
            chunk_totals[i] += chunk_totals[i - 1];
        }
        /* implicit barrier after single */

        /* Phase 3: apply offsets from previous chunks */
        if (tid > 0) {
            double offset = chunk_totals[tid - 1];
            for (int i = start; i < end; i++) {
                data[i] += offset;
            }
        }
    }

    free(chunk_totals);
}

int main(void) {
    double *data = (double *)malloc(N * sizeof(double));

    for (int i = 0; i < N; i++) {
        data[i] = lcg_rand_double() - 0.5;
    }

    omp_set_num_threads(4);
    parallel_prefix_sum(data, N);

    printf("scan[0]=%.10e\n", data[0]);
    printf("scan[999]=%.10e\n", data[999]);
    printf("scan[49999]=%.10e\n", data[49999]);
    printf("scan[99999]=%.10e\n", data[N - 1]);

    double checksum = 0.0;
    for (int i = 0; i < N; i++) checksum += data[i];
    printf("checksum=%.10e\n", checksum);

    free(data);
    return 0;
}
'''

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def verify(name, src, ref_src):
    """Compile and verify a fixed kernel for correctness against reference."""
    env = os.environ.copy()
    env['OMP_NUM_THREADS'] = '4'

    exe = f'/tmp/{name}_verify'
    r = subprocess.run(['gcc', '-fopenmp', '-O2', '-o', exe, src, '-lm'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL: {name} compilation error: {r.stderr}")
        return False

    ref_exe = f'/tmp/{name}_ref'
    r = subprocess.run(['gcc', '-O2', '-o', ref_exe, ref_src, '-lm'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL: {name} reference compilation error: {r.stderr}")
        return False

    r = subprocess.run([ref_exe], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"FAIL: {name} reference runtime error: {r.stderr}")
        return False
    ref_output = r.stdout.strip()
    print(f"{name} reference: {ref_output}")

    for threads in ['2', '4']:
        run_env = env.copy()
        run_env['OMP_NUM_THREADS'] = threads
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60,
                           env=run_env)
        if r.returncode != 0:
            print(f"FAIL: {name} runtime error (threads={threads}): {r.stderr}")
            return False
        par_output = r.stdout.strip()
        print(f"{name} parallel (threads={threads}): {par_output}")

        ref_lines = ref_output.split('\n')
        par_lines = par_output.split('\n')
        for rl, pl in zip(ref_lines, par_lines):
            rk, rv = rl.split('=', 1)
            pk, pv = pl.split('=', 1)
            if rk.strip() != pk.strip():
                print(f"FAIL: {name} output key mismatch: {rk} vs {pk}")
                return False
            try:
                rf, pf = float(rv), float(pv)
                if abs(rf - pf) > max(1e-3, abs(rf) * 1e-4):
                    print(f"FAIL: {name} value mismatch for {rk}: {rf} vs {pf}")
                    return False
            except ValueError:
                if rv.strip() != pv.strip():
                    print(f"FAIL: {name} string mismatch for {rk}: {rv} vs {pv}")
                    return False

    print(f"{name}: correct and deterministic, verified OK")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    kernels = {
        'histogram':   HISTOGRAM_FIXED,
        'jacobi':      JACOBI_FIXED,
        'nbody':       NBODY_FIXED,
        'convolve':    CONVOLVE_FIXED,
        'prefix_scan': PREFIX_SCAN_FIXED,
    }

    # Write all fixed source files
    for name, code in kernels.items():
        path = f'/app/src/{name}.c'
        write_file(path, code)
        print(f"Wrote fixed {name}.c")

    # Verify each against its sequential reference
    refs = {
        'histogram':   '/tests/ref_histogram.c',
        'jacobi':      '/tests/ref_jacobi.c',
        'nbody':       '/tests/ref_nbody.c',
        'convolve':    '/tests/ref_convolve.c',
        'prefix_scan': '/tests/ref_prefix_scan.c',
    }

    results = []
    for name in kernels:
        results.append(verify(name, f'/app/src/{name}.c', refs[name]))

    if all(results):
        print("\nAll five kernels fixed and verified successfully.")
    else:
        print("\nSome verifications failed.")
        sys.exit(1)
