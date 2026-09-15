#include "fp_oracle.h"
#include <fenv.h>
#include <math.h>
#include <string.h>
#include <stdint.h>
#include <limits.h>


static double bits_to_double(uint64_t bits) {
    double d;
    memcpy(&d, &bits, sizeof(d));
    return d;
}

static uint64_t double_to_bits(double d) {
    uint64_t bits;
    memcpy(&bits, &d, sizeof(bits));
    return bits;
}

decoded_fp64_t decode_binary64(uint64_t bits) {
    decoded_fp64_t result;

    result.sign = (bits >> 63) & 1;
    result.biased_exp = (bits >> 52) & 0x7FF;
    result.significand = bits & FP64_FRAC_MASK;
    result.nan_payload = 0;

    if (result.biased_exp == 0) {
        if (result.significand == 0) {
            /* FIX: Check sign bit to distinguish +0 from -0 */
            result.cls = result.sign ? FP_CLASS_NEG_ZERO : FP_CLASS_POS_ZERO;
            result.unbiased_exp = 0;
        } else {
            /* FIX: Subnormal exponent is 1 - bias = -1022, not 0 - bias = -1023.
               The biased exponent field is 0, but IEEE 754 defines the actual
               exponent for subnormals as e_min = 1 - bias. */
            result.unbiased_exp = 1 - FP64_EXP_BIAS;   /* = -1022 */
            result.cls = result.sign ? FP_CLASS_NEG_SUBNORMAL
                                     : FP_CLASS_POS_SUBNORMAL;
        }
    } else if (result.biased_exp == FP64_EXP_MAX) {
        if (result.significand == 0) {
            result.cls = result.sign ? FP_CLASS_NEG_INFINITY
                                     : FP_CLASS_POS_INFINITY;
            result.unbiased_exp = 0;
        } else {
            /* FIX: Check the quiet bit (bit 51) to distinguish qNaN from sNaN.
               If quiet bit is set -> quiet NaN; if clear -> signaling NaN. */
            if (result.significand & FP64_QUIET_BIT) {
                result.cls = FP_CLASS_QUIET_NAN;
            } else {
                result.cls = FP_CLASS_SIGNALING_NAN;
            }
            /* Payload is the significand bits below the quiet bit */
            result.nan_payload = result.significand & (FP64_QUIET_BIT - 1);
            result.unbiased_exp = 0;
        }
    } else {
        /* Normal number */
        result.unbiased_exp = result.biased_exp - FP64_EXP_BIAS;
        result.cls = result.sign ? FP_CLASS_NEG_NORMAL : FP_CLASS_POS_NORMAL;
    }

    return result;
}

uint64_t soft_nextafter(uint64_t x_bits, uint64_t y_bits, int *exceptions) {
    *exceptions = EXC_NONE;

    uint64_t ax = x_bits & ~FP64_SIGN_MASK;
    uint64_t ay = y_bits & ~FP64_SIGN_MASK;

    /* FIX: Check for NaN inputs.
       A value is NaN iff |bits| > INF_BITS (exponent all 1s, significand != 0).
       Return a quiet NaN without stepping the bit pattern. */
    if (ax > FP64_INF_BITS || ay > FP64_INF_BITS) {
        /* Return a quiet NaN (prefer x's NaN, else y's, with quiet bit set) */
        if (ax > FP64_INF_BITS)
            return x_bits | FP64_QUIET_BIT;
        return y_bits | FP64_QUIET_BIT;
    }

    /* FIX: Return y (not x) when x == y.
       This matters for nextafter(+0, -0) which must return -0. */
    if (x_bits == y_bits) {
        return y_bits;
    }

    uint64_t result;

    if (ax == 0) {
        /* FIX: When x is zero, compute the smallest subnormal toward y.
           If y is also zero (different sign), return y.
           Otherwise, construct smallest subnormal with y's sign. */
        if (ay == 0) {
            /* Both are zero but different signs (since x_bits != y_bits) */
            return y_bits;
        }
        /* Smallest subnormal with the sign of y */
        result = (y_bits & FP64_SIGN_MASK) | 1;
    } else if (ax > ay || ((x_bits ^ y_bits) & FP64_SIGN_MASK)) {
        /* Move toward zero (decrement magnitude) */
        result = x_bits - 1;
    } else {
        /* Move away from zero (increment magnitude) */
        result = x_bits + 1;
    }

    /* FIX: Set exception flags per IEEE 754 / C Annex F F.10.8.3:
       - overflow + inexact when result is infinite and x was finite
       - underflow + inexact when result is subnormal or zero
         (except for the both-zero early return above) */
    uint64_t result_exp = (result >> 52) & 0x7FF;
    uint64_t result_abs = result & ~FP64_SIGN_MASK;

    if (result_exp == FP64_EXP_MAX && result_abs == FP64_INF_BITS
        && ax < FP64_INF_BITS) {
        /* Stepped from finite to infinity */
        *exceptions = EXC_OVERFLOW | EXC_INEXACT;
    } else if (result_exp == 0) {
        /* Result is subnormal or zero */
        *exceptions = EXC_UNDERFLOW | EXC_INEXACT;
    }

    return result;
}

int soft_totalorder(uint64_t a_bits, uint64_t b_bits) {
    int64_t ia, ib;
    memcpy(&ia, &a_bits, sizeof(ia));
    memcpy(&ib, &b_bits, sizeof(ib));

    /* FIX: Use XOR with INT64_MAX (0x7FFFFFFFFFFFFFFF) for negative values.
       This flips only the lower 63 bits (magnitude), keeping the sign bit,
       which correctly reverses the magnitude ordering for negative values
       while keeping them in the negative int64 range.

       The old code used ~ia which flips ALL 64 bits including the sign,
       mapping negative doubles to large positive int64 values and
       breaking the ordering. */
    if (ia < 0) ia ^= INT64_MAX;
    if (ib < 0) ib ^= INT64_MAX;

    return ia <= ib;
}

uint64_t find_counterexample(int transform_id) {
    switch (transform_id) {
    case 0:
        /* x - x -> 0.0 is INVALID.
           Counterexample: x = +Inf.  Inf - Inf = NaN != +0.0 */
        return FP64_INF_BITS;

    case 1:
        /* x + 0 -> x is INVALID.
           Counterexample: x = -0.  (-0) + (+0) = +0 != -0 */
        return FP64_SIGN_MASK;   /* -0.0 */

    case 2:
        /* 0 * x -> 0.0 is INVALID.
           Counterexample: x = +Inf.  0 * Inf = NaN != +0.0 */
        return FP64_INF_BITS;

    case 3:
        /* x / x -> 1.0 is INVALID.
           Counterexample: x = +Inf.  Inf / Inf = NaN != 1.0 */
        return FP64_INF_BITS;

    case 4:
        /* x - y <-> -(y - x) is INVALID (y = 1.0).
           Counterexample: x = 1.0.
           1.0 - 1.0 = +0.0, -(1.0 - 1.0) = -(+0.0) = -0.0.
           +0.0 and -0.0 have different bit patterns. */
        return 0x3FF0000000000000ULL;  /* 1.0 */

    case 5:
        /* -x <-> 0 - x is INVALID.
           Counterexample: x = +0.0.
           -(+0.0) = -0.0, but 0.0 - (+0.0) = +0.0.
           Different bit patterns. */
        return 0x0000000000000000ULL;  /* +0.0 */

    default:
        return 0;
    }
}

void eval_rounding_modes(uint64_t a_bits, uint64_t b_bits, int op,
                         uint64_t results[4]) {
    double a = bits_to_double(a_bits);
    double b = bits_to_double(b_bits);

    /* FIX: Correct order — index 1 is DOWNWARD, index 2 is UPWARD */
    int modes[] = { FE_TONEAREST, FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO };

    int saved = fegetround();

    for (int i = 0; i < 4; i++) {
        fesetround(modes[i]);
        volatile double r;
        switch (op) {
            case 0: r = a + b; break;
            case 1: r = a - b; break;
            case 2: r = a * b; break;
            case 3: r = a / b; break;
            default: r = 0.0; break;
        }
        results[i] = double_to_bits(r);
    }

    fesetround(saved);
}
