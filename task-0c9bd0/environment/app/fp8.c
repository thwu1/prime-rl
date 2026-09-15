/* fp8.c - IEEE 754 compliant FP8 E4M3 arithmetic library
 *
 * Implement all functions declared in fp8_api.h.
 * See /app/spec.md for format details and requirements.
 *
 * Format: 1 sign bit, 4 exponent bits, 3 mantissa bits, bias=7.
 */

#include "fp8_api.h"
#include <math.h>
#include <string.h>

/* TODO: Implement all functions below. */

double fp8_to_float(uint8_t raw) {
    (void)raw;
    return 0.0;
}

uint8_t fp8_from_float(double value, int rounding) {
    (void)value; (void)rounding;
    return 0;
}

uint8_t fp8_add(uint8_t a, uint8_t b, int rounding) {
    (void)a; (void)b; (void)rounding;
    return 0;
}

uint8_t fp8_mul(uint8_t a, uint8_t b, int rounding) {
    (void)a; (void)b; (void)rounding;
    return 0;
}

uint8_t fp8_fma(uint8_t a, uint8_t b, uint8_t c, int rounding) {
    (void)a; (void)b; (void)c; (void)rounding;
    return 0;
}

int fp8_classify(uint8_t raw) {
    (void)raw;
    return 0;
}

int fp8_compare(uint8_t a, uint8_t b) {
    (void)a; (void)b;
    return 0;
}
