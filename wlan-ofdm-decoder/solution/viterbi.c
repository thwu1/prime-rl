/*
 * IEEE 802.11a Viterbi Decoder — K=7, Rate 1/2
 *
 * 64-state trellis, generator polynomials g0=0155, g1=0117 (octal).
 * Supports hard-decision inputs with erasures (value 2).
 *
 * Exported function:
 *   int viterbi_decode(const int *received, int n_data_bits, int *decoded)
 *     received: array of 2*n_data_bits values, each 0, 1, or 2 (erasure)
 *     decoded:  output array of n_data_bits decoded information bits
 *     returns:  0 on success, -1 on memory allocation failure
 */

#include <stdlib.h>
#include <string.h>

#define N_STATES 64
#define G0 0x6D  /* octal 0155 */
#define G1 0x4F  /* octal 0117 */
#define INF_METRIC 1000000

static int nxt[N_STATES][2];
static int eout[N_STATES][2][2];
static int trellis_ready = 0;

static int popcount_7(unsigned int x) {
    int c = 0;
    while (x) { c += x & 1; x >>= 1; }
    return c;
}

static void build_trellis(void) {
    int s, b, reg;
    if (trellis_ready) return;
    for (s = 0; s < N_STATES; s++) {
        for (b = 0; b < 2; b++) {
            reg = (s << 1) | b;
            nxt[s][b] = reg & 0x3F;
            eout[s][b][0] = popcount_7((unsigned)(reg & G0)) & 1;
            eout[s][b][1] = popcount_7((unsigned)(reg & G1)) & 1;
        }
    }
    trellis_ready = 1;
}

int viterbi_decode(const int *received, int n_data_bits, int *decoded) {
    int t, s, b, ns, bm, total, best;
    int r0, r1;
    int *pm, *npm, *tmp_ptr;
    int *tbp, *tbb;

    build_trellis();

    pm  = (int *)malloc((size_t)N_STATES * sizeof(int));
    npm = (int *)malloc((size_t)N_STATES * sizeof(int));
    tbp = (int *)malloc((size_t)n_data_bits * N_STATES * sizeof(int));
    tbb = (int *)malloc((size_t)n_data_bits * N_STATES * sizeof(int));

    if (!pm || !npm || !tbp || !tbb) {
        free(pm); free(npm); free(tbp); free(tbb);
        return -1;
    }

    /* Initialize path metrics */
    pm[0] = 0;
    for (s = 1; s < N_STATES; s++) pm[s] = INF_METRIC;

    /* Forward pass: ACS (Add-Compare-Select) */
    for (t = 0; t < n_data_bits; t++) {
        for (s = 0; s < N_STATES; s++) npm[s] = INF_METRIC;

        r0 = received[2 * t];
        r1 = received[2 * t + 1];

        for (s = 0; s < N_STATES; s++) {
            if (pm[s] >= INF_METRIC) continue;
            for (b = 0; b < 2; b++) {
                ns = nxt[s][b];
                bm = 0;
                if (r0 != 2) bm += (r0 != eout[s][b][0]);
                if (r1 != 2) bm += (r1 != eout[s][b][1]);

                total = pm[s] + bm;
                if (total < npm[ns]) {
                    npm[ns] = total;
                    tbp[t * N_STATES + ns] = s;
                    tbb[t * N_STATES + ns] = b;
                }
            }
        }

        tmp_ptr = pm; pm = npm; npm = tmp_ptr;
    }

    /* Find best final state */
    best = 0;
    for (s = 1; s < N_STATES; s++) {
        if (pm[s] < pm[best]) best = s;
    }

    /* Traceback */
    s = best;
    for (t = n_data_bits - 1; t >= 0; t--) {
        decoded[t] = tbb[t * N_STATES + s];
        s = tbp[t * N_STATES + s];
    }

    free(pm); free(npm); free(tbp); free(tbb);
    return 0;
}
