
#ifndef BF16_H
#define BF16_H

#include <stdint.h>

/* Rounding mode constants */
#define RM_RNE 0  /* Round to nearest, ties to even */
#define RM_RNA 1  /* Round to nearest, ties away from zero */
#define RM_RZ  2  /* Round toward zero */
#define RM_RU  3  /* Round toward +infinity */
#define RM_RD  4  /* Round toward -infinity */

/* Classification constants */
#define CLASS_ZERO      0
#define CLASS_SUBNORMAL 1
#define CLASS_NORMAL    2
#define CLASS_INFINITY  3
#define CLASS_NAN       4

/* Special raw values */
#define BF16_POS_ZERO  0x0000
#define BF16_NEG_ZERO  0x8000
#define BF16_POS_INF   0x7F80
#define BF16_NEG_INF   0xFF80
#define BF16_QNAN      0x7FC0
#define BF16_MAX_NORMAL 0x7F7F
#define BF16_MIN_NORMAL 0x0080

/**
 * Unpack a 16-bit bfloat16 value into its component fields.
 * Writes sign (0 or 1), biased exponent (0..255), and mantissa (0..127)
 * through the provided output pointers.
 */
void bf16_unpack(uint16_t raw, int *sign, int *exp, int *man);

/**
 * Pack component fields into a 16-bit bfloat16 value.
 */
uint16_t bf16_pack(int sign, int exp, int man);

/**
 * Classify a bfloat16 value.
 * Returns one of: CLASS_ZERO, CLASS_SUBNORMAL, CLASS_NORMAL,
 *                 CLASS_INFINITY, CLASS_NAN
 */
int bf16_classify(uint16_t raw);

/**
 * Convert a bfloat16 value to a double.
 * Must preserve signed zero and produce NaN/Inf as appropriate.
 */
double bf16_to_float(uint16_t raw);

/**
 * Convert a double to bfloat16 with the specified rounding mode (RM_*).
 */
uint16_t bf16_from_float(double value, int rm);

/**
 * Add two bfloat16 values with the specified rounding mode.
 */
uint16_t bf16_add(uint16_t a, uint16_t b, int rm);

/**
 * Multiply two bfloat16 values with the specified rounding mode.
 */
uint16_t bf16_mul(uint16_t a, uint16_t b, int rm);

#endif /* BF16_H */
