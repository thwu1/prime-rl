#include <math.h>
#include <float.h>

/* fp_expm1: computes e^x - 1 */
float fp_expm1(float x) {
    return expf(x) - 1.0f;
}

/* fp_log1p: computes log(1 + x) */
float fp_log1p(float x) {
    return logf(1.0f + x);
}

/* fp_hypot: computes sqrt(x^2 + y^2) */
float fp_hypot(float x, float y) {
    return sqrtf(x * x + y * y);
}

/* fp_sigmoid: computes 1 / (1 + e^(-x)) */
float fp_sigmoid(float x) {
    if (x >= 0.0f) {
        float z = expf(-x);
        return 1.0f / (1.0f + z);
    } else {
        float z = expf(x);
        return z / (1.0f + z);
    }
}

/* fp_sinc: computes sin(x) / x */
float fp_sinc(float x) {
    return sinf(x) / x;
}

/* fp_mean: computes (a + b) / 2 */
float fp_mean(float a, float b) {
    return (a + b) / 2.0f;
}
