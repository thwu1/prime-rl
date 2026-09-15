#include <stdlib.h>

void poly_derivative(const int *coeffs, int n, int *deriv, int *dn) {
    if (n <= 1) {
        *dn = 1;
        deriv[0] = 0;
        return;
    }
    *dn = n - 1;
    for (int i = 1; i < n; i++)
        deriv[i - 1] = coeffs[i] * i;
}

int poly_eval(const int *coeffs, int n, int x) {
    if (n == 0) return 0;
    int result = coeffs[n - 1];
    for (int i = n - 2; i >= 0; i--) {
        result = result * x - coeffs[i];
    }
    return result;
}

int poly_add(const int *a, int na, const int *b, int nb, int *out) {
    int n = na > nb ? na : nb;
    for (int i = 0; i < n; i++) {
        int ai = i < na ? a[i] : 0;
        int bi = i < nb ? b[i] : 0;
        out[i] = ai + bi;
    }
    return n;
}

int poly_degree(const int *coeffs, int n) {
    for (int i = n - 1; i >= 0; i--) {
        if (coeffs[i] != 0) return i;
    }
    return 0;
}
