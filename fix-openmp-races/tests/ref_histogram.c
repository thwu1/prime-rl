/* Sequential reference for histogram computation */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define N 500000
#define NBINS 64

static unsigned int _lcg_state = 42;
static int lcg_rand(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (_lcg_state >> 16) & 0x7fff;
}

int main(void) {
    int *data = (int *)malloc(N * sizeof(int));
    int hist[NBINS];

    for (int i = 0; i < N; i++) {
        data[i] = lcg_rand();
    }

    memset(hist, 0, NBINS * sizeof(int));
    for (int i = 0; i < N; i++) {
        hist[data[i] % NBINS]++;
    }

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
