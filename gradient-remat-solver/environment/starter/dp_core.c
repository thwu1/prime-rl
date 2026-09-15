
#include <stdlib.h>
#include <math.h>

/*
 * Flat 3D indexing: table[m][i][l] -> flat[m * s * s + i * s + l]
 * where s = n + 1.
 */
static inline int idx3(int m, int i, int l, int s) {
    return m * s * s + i * s + l;
}

/*
 * Compute the optimal scheduling table for a sequential chain of layers.
 *
 * Parameters:
 *   n       - number of layers (chain length)
 *   mmax    - maximum memory budget
 *   fw      - forward computation times, length n+1 (fw[n] = 0, padding)
 *   bw      - backward computation times, length n+1
 *   cw      - activation sizes (no grad), length n+2 (cw[n+1] = 0, padding)
 *   cbw     - activation sizes (with grad), length n+2 (cbw[n+1] = 0, padding)
 *   ftmp    - forward temporary memory, length n+1 (ftmp[n] = 0, padding)
 *   btmp    - backward temporary memory, length n+1
 *   opt     - output cost table, pre-allocated: (mmax+1) * (n+1) * (n+1)
 *   wtype   - output decision type, pre-allocated: same size; 1=type A, 0=type B
 *   wj      - output decision index, pre-allocated: same size; position for type B
 */
void compute_dp(
    int n, int mmax,
    const double *fw, const double *bw,
    const int *cw, const int *cbw,
    const int *ftmp, const int *btmp,
    double *opt, int *wtype, int *wj
) {
    int s = n + 1;
    int total = (mmax + 1) * s * s;
    double inf = INFINITY;
    int m, d, i, l, j, k;

    /* Initialize all entries */
    for (k = 0; k < total; k++) {
        opt[k] = inf;
        wtype[k] = -1;
        wj[k] = -1;
    }

    /* --- Base case: processing a single layer at position i --- */
    for (m = 0; m <= mmax; m++) {
        for (i = 0; i <= n; i++) {
            int la = cw[i + 1] + cbw[i + 1] + ftmp[i];
            int lb = cw[i] + cw[i + 1] + cbw[i] + btmp[i];
            int limit = la > lb ? la : lb;
            if (m >= limit) {
                opt[idx3(m, i, i, s)] = fw[i] + bw[i];
            }
        }
    }

    /* --- General case: subchains of increasing length d --- */
    for (m = 0; m <= mmax; m++) {
        for (d = 1; d <= n; d++) {
            for (i = 0; i <= n - d; i++) {
                l = i + d;

                /* Required memory for the forward sweep */
                int mmin = cw[l + 1] + cw[i + 1] + ftmp[i];
                for (j = i + 1; j < l; j++) {
                    int v = cw[l + 1] + cw[j] + cw[j + 1] + ftmp[j];
                    if (v > mmin) mmin = v;
                }
                if (m < mmin) continue;

                double best = inf;
                int bt = -1, bj_val = -1;

                /* --- Type B decisions: store x_j --- */
                for (j = i + 1; j <= l; j++) {
                    if (m >= cw[j]) {
                        double fsum = 0.0;
                        for (k = i; k <= j; k++) fsum += fw[k];
                        double cost = fsum
                            + opt[idx3(m - cw[j], j, l, s)]
                            + opt[idx3(m, i, j - 1, s)];
                        if (cost < best) {
                            best = cost;
                            bt = 0;
                            bj_val = j;
                        }
                    }
                }

                /* --- Type A decision: store xbar_{i+1} --- */
                if (m >= cbw[i + 1]) {
                    double cost = opt[idx3(m, i, i, s)]
                        + opt[idx3(m - cbw[i + 1], i + 1, l, s)];
                    if (cost < best) {
                        best = cost;
                        bt = 1;
                        bj_val = -1;
                    }
                }

                opt[idx3(m, i, l, s)] = best;
                wtype[idx3(m, i, l, s)] = bt;
                wj[idx3(m, i, l, s)] = bj_val;
            }
        }
    }
}
