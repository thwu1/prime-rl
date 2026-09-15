#include "fp_oracle.h"
#include <fenv.h>
#include <math.h>
#include <string.h>
#include <stdint.h>


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
            result.cls = FP_CLASS_POS_ZERO;
            result.unbiased_exp = 0;
        } else {
            result.unbiased_exp = result.biased_exp - FP64_EXP_BIAS;
            result.cls = result.sign ? FP_CLASS_NEG_SUBNORMAL
                                     : FP_CLASS_POS_SUBNORMAL;
        }
    } else if (result.biased_exp == FP64_EXP_MAX) {
        if (result.significand == 0) {
            result.cls = result.sign ? FP_CLASS_NEG_INFINITY
                                     : FP_CLASS_POS_INFINITY;
            result.unbiased_exp = 0;
        } else {
            result.cls = FP_CLASS_QUIET_NAN;
            result.nan_payload = result.significand & (FP64_QUIET_BIT - 1);
            result.unbiased_exp = 0;
        }
    } else {
        result.unbiased_exp = result.biased_exp - FP64_EXP_BIAS;
        result.cls = result.sign ? FP_CLASS_NEG_NORMAL : FP_CLASS_POS_NORMAL;
    }

    return result;
}

uint64_t soft_nextafter(uint64_t x_bits, uint64_t y_bits, int *exceptions) {
    *exceptions = EXC_NONE;

    if (x_bits == y_bits) {
        return x_bits;
    }

    uint64_t ax = x_bits & ~FP64_SIGN_MASK;
    uint64_t ay = y_bits & ~FP64_SIGN_MASK;

    uint64_t result;

    if (ax == 0) {
        result = x_bits;
    } else if (ax > ay || ((x_bits | y_bits) & FP64_SIGN_MASK)) {
        result = x_bits - 1;
    } else {
        result = x_bits + 1;
    }

    return result;
}

int soft_totalorder(uint64_t a_bits, uint64_t b_bits) {
    int64_t ia, ib;
    memcpy(&ia, &a_bits, sizeof(ia));
    memcpy(&ib, &b_bits, sizeof(ib));

    if (ia < 0) ia = ~ia;
    if (ib < 0) ib = ~ib;

    return ia <= ib;
}

uint64_t find_counterexample(int transform_id) {
    (void)transform_id;
    return 0;
}

void eval_rounding_modes(uint64_t a_bits, uint64_t b_bits, int op,
                         uint64_t results[4]) {
    double a = bits_to_double(a_bits);
    double b = bits_to_double(b_bits);

    int modes[] = { FE_TONEAREST, FE_UPWARD, FE_DOWNWARD, FE_TOWARDZERO };

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
