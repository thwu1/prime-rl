/* Parallel 1D convolution using OpenMP */

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
    memset(output, 0, n * sizeof(double));

    #pragma omp parallel for
    for (int k = 0; k < m; k++) {
        for (int i = k; i < n; i++) {
            output[i] += filter[k] * signal[i - k];
        }
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
