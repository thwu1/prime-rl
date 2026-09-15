/* SAXPY: y[i] = a * x[i] + y[i] */
#include <stdio.h>
#include <stdlib.h>

void saxpy_ref(int n, float a, const float *restrict x, float *restrict y) {
    for (int i = 0; i < n; i++) {
        y[i] = a * x[i] + y[i];
    }
}

int main(void) {
    const int n = 1024;
    const float a = 2.5f;
    float *x = (float *)malloc(n * sizeof(float));
    float *y = (float *)malloc(n * sizeof(float));
    if (!x || !y) return 1;

    for (int i = 0; i < n; i++) {
        x[i] = (float)(i % 100) * 0.1f;
        y[i] = (float)(i % 50) * 0.2f;
    }

    saxpy_ref(n, a, x, y);

    double sum = 0.0;
    for (int i = 0; i < n; i++) sum += (double)y[i];
    printf("SAXPY checksum: %.6f\n", sum);

    free(x);
    free(y);
    return 0;
}
