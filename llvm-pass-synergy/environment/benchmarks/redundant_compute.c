/* Benchmark: redundant computations, common subexpressions, loop invariants */

int square(int x) { return x * x; }

int compute_distance_sum(int x1, int y1, int x2, int y2) {
    int dx = x2 - x1;
    int dy = y2 - y1;
    int dist_sq = dx * dx + dy * dy;
    /* Redundant recomputation */
    int dx_sq = dx * dx;
    int dy_sq = dy * dy;
    int extra = (dx * dx) + (dy * dy);
    return dist_sq + dx_sq + dy_sq + extra;
}

void scale_array(int *data, int *result, int n, int factor) {
    for (int i = 0; i < n; i++) {
        /* Loop-invariant: factor*factor+factor+1 */
        int scale = factor * factor + factor + 1;
        result[i] = data[i] * scale + scale;
    }
}

int polynomial_eval(int x, int a, int b, int c, int d) {
    int x2 = x * x;
    int x3 = x * x * x;  /* Could reuse x2 */
    int t1 = a * x3;
    int t2 = b * x2;
    int t3 = c * x;
    int check = a * x * x * x + b * x * x;  /* Fully redundant */
    if (check != t1 + t2) return -1;  /* Dead branch */
    return t1 + t2 + t3 + d;
}

void diagonal_sum(int *matrix, int *diag, int n) {
    for (int i = 0; i < n; i++) {
        diag[i] = matrix[i * n + i];
    }
}

int accumulate_scaled(int *arr, int n, int base, int exp) {
    int sum = 0;
    for (int i = 0; i < n; i++) {
        /* Loop invariant: base^exp doesn't change */
        int power = 1;
        for (int j = 0; j < exp; j++) power *= base;
        sum += arr[i] * power;
    }
    return sum;
}

int triple_redundant(int a, int b) {
    int r1 = (a + b) * (a - b);
    int r2 = (a + b) * (a - b);
    int r3 = (a + b) * (a - b);
    return r1 + r2 + r3;
}
