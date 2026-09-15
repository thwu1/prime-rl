/* fp8_api.h - IEEE 754 compliant FP8 E4M3 arithmetic library API
 *
 * Format: 1 sign bit, 4 exponent bits, 3 mantissa bits, bias=7.
 * See /app/spec.md for full specification.
 */

#ifndef FP8_API_H
#define FP8_API_H

#include <stdint.h>

/* Rounding mode constants */
#define FP8_RNE 0  /* Round to nearest, ties to even */
#define FP8_RNA 1  /* Round to nearest, ties away from zero */
#define FP8_RU  2  /* Round toward +infinity */
#define FP8_RD  3  /* Round toward -infinity */
#define FP8_RZ  4  /* Round toward zero */

/* Classification constants */
#define FP8_CLASS_NORMAL    0
#define FP8_CLASS_SUBNORMAL 1
#define FP8_CLASS_ZERO      2
#define FP8_CLASS_INFINITY  3
#define FP8_CLASS_NAN       4

/* Compare: unordered result (NaN involved) */
#define FP8_CMP_UNORDERED   2

/* Decode FP8 raw byte to double (preserves signed zero, NaN, Inf) */
double fp8_to_float(uint8_t raw);

/* Encode double to FP8 with specified rounding mode */
uint8_t fp8_from_float(double value, int rounding);

/* IEEE 754 compliant addition */
uint8_t fp8_add(uint8_t a, uint8_t b, int rounding);

/* IEEE 754 compliant multiplication */
uint8_t fp8_mul(uint8_t a, uint8_t b, int rounding);

/* Fused multiply-add: a*b + c with single rounding */
uint8_t fp8_fma(uint8_t a, uint8_t b, uint8_t c, int rounding);

/* Classify: returns FP8_CLASS_* constant */
int fp8_classify(uint8_t raw);

/* Compare: returns -1, 0, 1, or FP8_CMP_UNORDERED */
int fp8_compare(uint8_t a, uint8_t b);

#endif /* FP8_API_H */
