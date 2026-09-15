
#include "bf16.h"
#include <math.h>
#include <stdint.h>

void bf16_unpack(uint16_t raw, int *sign, int *exp, int *man) {
    /* TODO: Extract sign, biased exponent, and mantissa fields */
}

uint16_t bf16_pack(int sign, int exp, int man) {
    /* TODO: Combine fields into a 16-bit raw value */
    return 0;
}

int bf16_classify(uint16_t raw) {
    /* TODO: Return the CLASS_* constant for this value */
    return -1;
}

double bf16_to_float(uint16_t raw) {
    /* TODO: Convert raw bfloat16 to double, handling all categories */
    return 0.0;
}

uint16_t bf16_from_float(double value, int rm) {
    /* TODO: Convert double to bfloat16 with rounding mode rm (RM_* constant) */
    return 0;
}

uint16_t bf16_add(uint16_t a, uint16_t b, int rm) {
    /* TODO: IEEE 754 addition with rounding mode */
    return 0;
}

uint16_t bf16_mul(uint16_t a, uint16_t b, int rm) {
    /* TODO: IEEE 754 multiplication with rounding mode */
    return 0;
}
