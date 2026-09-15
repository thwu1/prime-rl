/* Parallel histogram computation using OpenMP */

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

        /* Merge local histograms into global histogram */
        for (int i = 0; i < nbins; i++) {
            hist[i] += local_hist[i];
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
