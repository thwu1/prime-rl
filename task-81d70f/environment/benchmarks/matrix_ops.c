/* Matrix operations with saturating arithmetic helpers */

static int sat_add(int a, int b) {
    long long r = (long long)a + b;
    if (r > 2147483647) return 2147483647;
    if (r < -2147483647 - 1) return -2147483647 - 1;
    return (int)r;
}

static int sat_mul(int a, int b) {
    long long r = (long long)a * b;
    if (r > 2147483647) return 2147483647;
    if (r < -2147483647 - 1) return -2147483647 - 1;
    return (int)r;
}

static int clamp_val(int v, int lo, int hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

void mat_mul_sat(int *A, int *B, int *C, int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            int s = 0;
            for (int k = 0; k < n; k++)
                s = sat_add(s, sat_mul(A[i*n+k], B[k*n+j]));
            C[i*n+j] = clamp_val(s, -1000000, 1000000);
        }
}

void mat_add_sat(int *A, int *B, int *C, int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            C[i*n+j] = sat_add(A[i*n+j], B[i*n+j]);
}

int mat_trace(int *A, int n) {
    int t = 0;
    for (int i = 0; i < n; i++)
        t = sat_add(t, A[i*n+i]);
    return t;
}

void mat_scale(int *A, int scalar, int *C, int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            C[i*n+j] = sat_mul(A[i*n+j], scalar);
}

int mat_frobenius_approx(int *A, int n) {
    int sum = 0;
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            int v = A[i*n+j];
            sum = sat_add(sum, sat_mul(v, v));
        }
    return sum;
}
