/* Sobol quasi-random sequence generator using Gray code enumeration.
   Direction numbers from Joe & Kuo (2010). */

#include <string.h>
#include "qrng.h"

#define BITS 30
#define MAX_DIM 6

static const int jk_degree[] = {1, 2, 3, 3, 4};
static const int jk_a[] = {0, 1, 1, 2, 1};
static const int jk_m_init[][4] = {
    {1, 0, 0, 0},
    {1, 1, 0, 0},
    {1, 1, 1, 0},
    {1, 3, 1, 0},
    {1, 1, 3, 3},
};

static unsigned int direction_numbers[MAX_DIM][BITS];

static int rightmost_zero_bit(unsigned int n) {
    int pos = 0;
    while ((n >> pos) & 1) pos++;
    return pos;
}

void sobol_init(int dim) {
    int d, i, k, s, a;
    unsigned int v[BITS];

    if (dim < 1 || dim > MAX_DIM) return;

    /* Dimension 1: Van der Corput base-2 */
    for (i = 0; i < BITS; i++) {
        direction_numbers[0][i] = 1u << (BITS - 1 - i);
    }

    for (d = 1; d < dim; d++) {
        s = jk_degree[d - 1];
        a = jk_a[d - 1];

        for (i = 0; i < BITS; i++) v[i] = 0;

        for (i = 0; i < s && i < BITS; i++) {
            v[i] = (unsigned int)jk_m_init[d - 1][i] << (BITS - 1 - i);
        }
        for (i = s; i < BITS; i++) {
            v[i] = v[i - s] ^ (v[i - s] >> s);
            for (k = 1; k < s; k++) {
                if ((a >> (s - 1 - k)) & 1) {
                    v[i] ^= v[i - k];
                }
            }
        }
        for (i = 0; i < BITS; i++) {
            direction_numbers[d][i] = v[i];
        }
    }
}

void sobol_generate(int dim, int n, double *output) {
    double scale = 1.0 / (1u << BITS);
    unsigned int x[MAX_DIM];
    int i, d, c;

    memset(x, 0, sizeof(unsigned int) * MAX_DIM);

    for (i = 0; i < n; i++) {
        if (i == 0) {
            for (d = 0; d < dim; d++) {
                output[d] = 0.0;
            }
        } else {
            c = rightmost_zero_bit(i);
            for (d = 0; d < dim; d++) {
                x[d] ^= direction_numbers[d][c];
                output[i * dim + d] = x[d] * scale;
            }
        }
    }
}
