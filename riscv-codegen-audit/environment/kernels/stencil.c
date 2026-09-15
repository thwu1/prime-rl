/* 1-D 3-point weighted stencil (smoothing / blur) */
#include <stdio.h>
#include <stdlib.h>

void stencil_ref(int n, const float *restrict input, float *restrict output) {
    output[0]     = input[0];
    output[n - 1] = input[n - 1];
    for (int i = 1; i < n - 1; i++) {
        output[i] = 0.25f * input[i - 1]
                   + 0.50f * input[i]
                   + 0.25f * input[i + 1];
    }
}

int main(void) {
    const int n = 2048;
    float *input  = (float *)malloc(n * sizeof(float));
    float *output = (float *)malloc(n * sizeof(float));
    if (!input || !output) return 1;

    for (int i = 0; i < n; i++) {
        input[i] = (float)(i % 100) * 0.1f + 1.0f;
    }

    stencil_ref(n, input, output);

    double sum = 0.0;
    for (int i = 0; i < n; i++) sum += (double)output[i];
    printf("STENCIL checksum: %.6f\n", sum);

    free(input);
    free(output);
    return 0;
}
