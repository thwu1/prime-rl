/* Sequential reference for 1D convolution */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define SIGNAL_LEN 200000
#define FILTER_LEN 127

static unsigned int _lcg_state = 31415;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
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

    /* Sequential convolution: output[i] = sum_{k} filter[k] * signal[i-k] */
    for (int i = 0; i < SIGNAL_LEN; i++) {
        double sum = 0.0;
        int k_max = (i < FILTER_LEN - 1) ? i : FILTER_LEN - 1;
        for (int k = 0; k <= k_max; k++) {
            sum += filter[k] * signal[i - k];
        }
        output[i] = sum;
    }

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
