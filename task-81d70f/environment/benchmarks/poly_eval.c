/* Fixed-point polynomial arithmetic (Q16.16 format) */

static int fp_mul(int a, int b) {
    return (int)(((long long)a * b) >> 16);
}

static int fp_abs(int x) { return x < 0 ? -x : x; }

static int fp_from_int(int x) { return x << 16; }

int horner_eval(const int *coeffs, int degree, int x) {
    int result = coeffs[degree];
    for (int i = degree - 1; i >= 0; i--)
        result = fp_mul(result, x) + coeffs[i];
    return result;
}

void poly_derivative(const int *in, int degree, int *out) {
    for (int i = 0; i < degree; i++)
        out[i] = fp_mul(in[i + 1], fp_from_int(i + 1));
}

void poly_eval_batch(const int *coeffs, int degree,
                     const int *xs, int *ys, int n) {
    for (int i = 0; i < n; i++)
        ys[i] = horner_eval(coeffs, degree, xs[i]);
}

int newton_root(const int *coeffs, int degree,
                const int *deriv, int deriv_deg,
                int x0, int tol, int max_iter) {
    int x = x0;
    for (int iter = 0; iter < max_iter; iter++) {
        int fx = horner_eval(coeffs, degree, x);
        if (fp_abs(fx) < tol) break;
        int dfx = horner_eval(deriv, deriv_deg, x);
        if (dfx == 0) break;
        x -= (int)(((long long)fx << 16) / dfx);
    }
    return x;
}

void lagrange_interp(const int *xs, const int *ys, int n,
                     const int *eval_xs, int *eval_ys, int m) {
    for (int k = 0; k < m; k++) {
        int sum = 0;
        for (int i = 0; i < n; i++) {
            int num = fp_from_int(1);
            int den = fp_from_int(1);
            for (int j = 0; j < n; j++) {
                if (j == i) continue;
                num = fp_mul(num, eval_xs[k] - xs[j]);
                den = fp_mul(den, xs[i] - xs[j]);
            }
            int basis = (den != 0) ? (int)(((long long)num << 16) / den) : 0;
            sum += fp_mul(ys[i], basis);
        }
        eval_ys[k] = sum;
    }
}
