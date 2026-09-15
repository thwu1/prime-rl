/* Sequential reference for inclusive prefix sum */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#define N 100000

static unsigned int _lcg_state = 54321;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
}

int main(void) {
    double *data = (double *)malloc(N * sizeof(double));

    for (int i = 0; i < N; i++) {
        data[i] = lcg_rand_double() - 0.5;
    }

    /* Sequential inclusive prefix sum */
    for (int i = 1; i < N; i++) {
        data[i] += data[i - 1];
    }

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
