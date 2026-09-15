#ifndef FP_ORACLE_H
#define FP_ORACLE_H

#include <stdint.h>


typedef enum {
    FP_CLASS_POS_ZERO        = 0,
    FP_CLASS_NEG_ZERO        = 1,
    FP_CLASS_POS_SUBNORMAL   = 2,
    FP_CLASS_NEG_SUBNORMAL   = 3,
    FP_CLASS_POS_NORMAL      = 4,
    FP_CLASS_NEG_NORMAL      = 5,
    FP_CLASS_POS_INFINITY    = 6,
    FP_CLASS_NEG_INFINITY    = 7,
    FP_CLASS_QUIET_NAN       = 8,
    FP_CLASS_SIGNALING_NAN   = 9
} fp_class_t;

typedef struct {
    int sign;              /* 0 = positive, 1 = negative */
    int biased_exp;        /* raw exponent field (0-2047) */
    int unbiased_exp;      /* actual exponent value */
    uint64_t significand;  /* 52-bit fraction field (raw bits) */
    fp_class_t cls;        /* classification */
    uint64_t nan_payload;  /* NaN payload (valid only for NaN classes) */
} decoded_fp64_t;

/* Exception flag constants */
#define EXC_NONE      0
#define EXC_INVALID   (1 << 0)
#define EXC_DIVBYZERO (1 << 1)
#define EXC_OVERFLOW  (1 << 2)
#define EXC_UNDERFLOW (1 << 3)
#define EXC_INEXACT   (1 << 4)

/* Bit layout constants for IEEE 754 binary64 */
#define FP64_SIGN_MASK     ((uint64_t)1 << 63)
#define FP64_EXP_MASK      ((uint64_t)0x7FF << 52)
#define FP64_FRAC_MASK     (((uint64_t)1 << 52) - 1)
#define FP64_QUIET_BIT     ((uint64_t)1 << 51)
#define FP64_EXP_BIAS      1023
#define FP64_EXP_MAX       2047
#define FP64_INF_BITS      ((uint64_t)0x7FF << 52)

/*
 * Decode a binary64 IEEE 754 value from its bit representation.
 */
decoded_fp64_t decode_binary64(uint64_t bits);

/*
 * Compute nextafter(x, y) using only bit manipulation.
 * Sets *exceptions to the appropriate IEEE 754 exception flags.
 * Returns the result as a uint64_t bit pattern.
 */
uint64_t soft_nextafter(uint64_t x_bits, uint64_t y_bits, int *exceptions);

/*
 * Implement the IEEE 754 totalOrder predicate.
 * Returns 1 if totalOrder(x, y) is true, 0 otherwise.
 */
int soft_totalorder(uint64_t a_bits, uint64_t b_bits);

/*
 * Find a counterexample (as a binary64 bit pattern) that demonstrates
 * the given algebraic transformation is invalid under IEEE 754.
 *
 * Transform IDs:
 *   0: x - x -> 0.0
 *   1: x + 0 -> x
 *   2: 0 * x -> 0.0
 *   3: x / x -> 1.0
 *   4: x - y <-> -(y - x)   (y is always 1.0)
 *   5: -x <-> 0 - x
 */
uint64_t find_counterexample(int transform_id);

/*
 * Evaluate a binary operation (a op b) under all four IEEE 754 rounding modes.
 * op: 0=add, 1=sub, 2=mul, 3=div
 * results[0] = FE_TONEAREST
 * results[1] = FE_DOWNWARD
 * results[2] = FE_UPWARD
 * results[3] = FE_TOWARDZERO
 */
void eval_rounding_modes(uint64_t a_bits, uint64_t b_bits, int op,
                         uint64_t results[4]);

#endif /* FP_ORACLE_H */
