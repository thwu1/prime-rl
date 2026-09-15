#include <math.h>
#include <float.h>

/* Fixed fp_expm1: use C99 expm1f to avoid catastrophic cancellation */
float fp_expm1(float x) {
    return expm1f(x);
}

/* Fixed fp_log1p: use C99 log1pf to avoid cancellation */
float fp_log1p(float x) {
    return log1pf(x);
}

/* Fixed fp_hypot: use C99 hypotf to avoid intermediate overflow */
float fp_hypot(float x, float y) {
    return hypotf(x, y);
}

/* fp_sigmoid: already numerically stable, kept as-is */
float fp_sigmoid(float x) {
    if (x >= 0.0f) {
        float z = expf(-x);
        return 1.0f / (1.0f + z);
    } else {
        float z = expf(x);
        return z / (1.0f + z);
    }
}

/* Fixed fp_sinc: guard x==0 to return 1.0 instead of 0/0=NaN */
float fp_sinc(float x) {
    if (x == 0.0f) return 1.0f;
    return sinf(x) / x;
}

/* Fixed fp_mean: divide first to avoid intermediate overflow */
float fp_mean(float a, float b) {
    return a / 2.0f + b / 2.0f;
}
