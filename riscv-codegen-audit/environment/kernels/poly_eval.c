/* Polynomial evaluation via Horner's method over an array of points */
#include <stdio.h>
#include <stdlib.h>

void poly_eval_ref(int n_points, int degree, const float *coeffs,
                   const float *restrict points, float *restrict results) {
    for (int i = 0; i < n_points; i++) {
        float x = points[i];
        float r = coeffs[degree];
        for (int d = degree - 1; d >= 0; d--) {
            r = r * x + coeffs[d];
        }
        results[i] = r;
    }
}

int main(void) {
    const int n_points = 512;
    const int degree = 7;
    float coeffs[] = {1.0f, -0.5f, 0.25f, -0.125f,
                      0.0625f, -0.03125f, 0.015625f, -0.0078125f};
    float *points  = (float *)malloc(n_points * sizeof(float));
    float *results = (float *)malloc(n_points * sizeof(float));
    if (!points || !results) return 1;

    for (int i = 0; i < n_points; i++) {
        points[i] = (float)(i - n_points / 2) * 0.01f;
    }

    poly_eval_ref(n_points, degree, coeffs, points, results);

    double sum = 0.0;
    for (int i = 0; i < n_points; i++) sum += (double)results[i];
    printf("POLYEVAL checksum: %.6f\n", sum);

    free(points);
    free(results);
    return 0;
}
