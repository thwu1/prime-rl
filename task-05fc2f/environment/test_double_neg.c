/*
 * Test: double-precision floating-point negation.
 * Negating a double flips the sign bit (bit 63 in IEEE 754).
 * If the wrong bit is flipped, the result is corrupted.
 *
 * Returns 0 on success, non-zero on failure.
 */
double negate_double(double x) {
    return -x;
}

int main() {
    double a = 5.0;
    double b = negate_double(a);

    /* b should be -5.0, so it must be negative */
    if (b > 0.0) return 1;

    /* a + b should be exactly 0.0 */
    double sum = a + b;
    if (sum > 0.001) return 2;
    if (sum < -0.001) return 2;

    /* Negating again should recover the original value */
    double c = negate_double(b);
    double diff = c - a;
    if (diff > 0.001) return 3;
    if (diff < -0.001) return 3;

    /* Test with a different value */
    double d = 123.456;
    double e = -d;
    double sum2 = d + e;
    if (sum2 > 0.001) return 4;
    if (sum2 < -0.001) return 4;

    return 0;
}
