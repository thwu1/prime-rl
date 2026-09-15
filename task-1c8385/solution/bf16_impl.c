
/*
 * Complete bfloat16 arithmetic implementation.
 * Uses double as exact intermediate precision (bfloat16 p=8 << double p=53).
 */

#include "bf16.h"
#include <math.h>
#include <stdint.h>

#define BIAS 127

void bf16_unpack(uint16_t raw, int *sign, int *exp, int *man) {
    raw &= 0xFFFF;
    *sign = (raw >> 15) & 1;
    *exp  = (raw >> 7) & 0xFF;
    *man  = raw & 0x7F;
}

uint16_t bf16_pack(int sign, int exp, int man) {
    return (uint16_t)(((sign & 1) << 15) | ((exp & 0xFF) << 7) | (man & 0x7F));
}

int bf16_classify(uint16_t raw) {
    int s, e, m;
    bf16_unpack(raw, &s, &e, &m);
    if (e == 0xFF) return m ? CLASS_NAN : CLASS_INFINITY;
    if (e == 0)    return m ? CLASS_SUBNORMAL : CLASS_ZERO;
    return CLASS_NORMAL;
}

double bf16_to_float(uint16_t raw) {
    int sign, exp, man;
    bf16_unpack(raw, &sign, &exp, &man);
    if (exp == 0xFF) {
        if (man) return NAN;
        return sign ? -INFINITY : INFINITY;
    }
    double val;
    if (exp == 0)
        val = ldexp((double)man, -133);
    else
        val = ldexp((double)(128 + man), exp - 134);
    return sign ? -val : val;
}

/* ---- Internal helpers ---- */

typedef struct { double val; int cls; int sign; } bf16_info;

static bf16_info bf16_exact(uint16_t raw) {
    bf16_info r;
    int exp, man;
    bf16_unpack(raw, &r.sign, &exp, &man);
    if (exp == 0xFF) {
        r.cls = man ? CLASS_NAN : CLASS_INFINITY;
        r.val = 0;
        return r;
    }
    if (exp == 0 && man == 0) {
        r.cls = CLASS_ZERO;
        r.val = 0;
        return r;
    }
    r.cls = (exp == 0) ? CLASS_SUBNORMAL : CLASS_NORMAL;
    if (exp == 0)
        r.val = ldexp((double)man, -133);
    else
        r.val = ldexp((double)(128 + man), exp - 134);
    if (r.sign) r.val = -r.val;
    return r;
}

/*
 * Round a positive exact double to bf16 with given sign and rounding mode.
 * val must be >= 0. sign is the output sign bit.
 */
static uint16_t round_to_bf16(double val, int sign, int rm) {
    if (val == 0.0) return bf16_pack(sign, 0, 0);

    /* Use frexp for exact exponent extraction (avoids log2 imprecision) */
    int exp_raw;
    double frac = frexp(val, &exp_raw);
    int exp_u = exp_raw - 1;       /* val = sig * 2^exp_u, sig in [1, 2) */
    int exp_biased = exp_u + BIAS;

    /* Overflow check */
    if (exp_biased >= 255) {
        if (rm == RM_RZ || (rm == RM_RU && sign) || (rm == RM_RD && !sign))
            return bf16_pack(sign, 254, 0x7F);
        return bf16_pack(sign, 255, 0);
    }

    int man_int;
    double remainder;

    if (exp_biased >= 1) {
        /* Normal range: sig = 2*frac in [1,2), man_exact = (sig-1)*128 */
        double sig = ldexp(frac, 1);
        double man_exact = (sig - 1.0) * 128.0;
        man_int = (int)man_exact;
        remainder = man_exact - man_int;
    } else {
        /* Subnormal range: value = man * 2^(-133) */
        double man_exact = ldexp(val, 133);
        man_int = (int)man_exact;
        remainder = man_exact - man_int;
        exp_biased = 0;
    }

    /* Rounding decision */
    int lsb = man_int & 1;
    int inexact = (remainder > 0.0);
    int round_up = 0;

    switch (rm) {
    case RM_RNE:
        round_up = (remainder > 0.5) || (remainder == 0.5 && lsb);
        break;
    case RM_RNA:
        round_up = (remainder >= 0.5);
        break;
    case RM_RZ:
        break;
    case RM_RU:
        round_up = (!sign && inexact);
        break;
    case RM_RD:
        round_up = (sign && inexact);
        break;
    }

    if (round_up) man_int++;

    /* Mantissa carry / overflow */
    if (exp_biased > 0 && man_int >= 128) {
        man_int = 0;
        exp_biased++;
        if (exp_biased >= 255) {
            if (rm == RM_RZ || (rm == RM_RU && sign) || (rm == RM_RD && !sign))
                return bf16_pack(sign, 254, 0x7F);
            return bf16_pack(sign, 255, 0);
        }
    } else if (exp_biased == 0 && man_int >= 128) {
        /* Subnormal overflow -> promote to min normal */
        man_int = 0;
        exp_biased = 1;
    }

    return bf16_pack(sign, exp_biased, man_int & 0x7F);
}

/* ---- Public API ---- */

uint16_t bf16_from_float(double value, int rm) {
    if (isnan(value))  return BF16_QNAN;
    if (isinf(value))  return value < 0 ? BF16_NEG_INF : BF16_POS_INF;
    if (value == 0.0)  return copysign(1.0, value) < 0 ? BF16_NEG_ZERO : BF16_POS_ZERO;

    int sign = value < 0;
    return round_to_bf16(fabs(value), sign, rm);
}

uint16_t bf16_add(uint16_t a, uint16_t b, int rm) {
    bf16_info ai = bf16_exact(a);
    bf16_info bi = bf16_exact(b);

    /* NaN propagation */
    if (ai.cls == CLASS_NAN || bi.cls == CLASS_NAN) return BF16_QNAN;

    /* Infinity cases */
    if (ai.cls == CLASS_INFINITY && bi.cls == CLASS_INFINITY) {
        return (ai.sign == bi.sign) ? (a & 0xFFFF) : BF16_QNAN;
    }
    if (ai.cls == CLASS_INFINITY) return a & 0xFFFF;
    if (bi.cls == CLASS_INFINITY) return b & 0xFFFF;

    /* Zero cases */
    if (ai.cls == CLASS_ZERO && bi.cls == CLASS_ZERO) {
        if (ai.sign == bi.sign) return a & 0xFFFF;
        return (rm == RM_RD) ? BF16_NEG_ZERO : BF16_POS_ZERO;
    }
    if (ai.cls == CLASS_ZERO) return b & 0xFFFF;
    if (bi.cls == CLASS_ZERO) return a & 0xFFFF;

    /* Exact sum (double has enough precision for bfloat16 add) */
    double result = ai.val + bi.val;
    if (result == 0.0)
        return (rm == RM_RD) ? BF16_NEG_ZERO : BF16_POS_ZERO;

    int rsign = result < 0;
    return round_to_bf16(fabs(result), rsign, rm);
}

uint16_t bf16_mul(uint16_t a, uint16_t b, int rm) {
    bf16_info ai = bf16_exact(a);
    bf16_info bi = bf16_exact(b);
    int rsign = ai.sign ^ bi.sign;

    /* NaN propagation */
    if (ai.cls == CLASS_NAN || bi.cls == CLASS_NAN) return BF16_QNAN;

    /* Inf * 0 = NaN */
    if ((ai.cls == CLASS_INFINITY && bi.cls == CLASS_ZERO) ||
        (bi.cls == CLASS_INFINITY && ai.cls == CLASS_ZERO))
        return BF16_QNAN;

    /* Inf * nonzero */
    if (ai.cls == CLASS_INFINITY || bi.cls == CLASS_INFINITY)
        return bf16_pack(rsign, 255, 0);

    /* Zero * finite */
    if (ai.cls == CLASS_ZERO || bi.cls == CLASS_ZERO)
        return bf16_pack(rsign, 0, 0);

    /* Exact product (double has enough precision for bfloat16 mul) */
    double result = fabs(ai.val) * fabs(bi.val);
    return round_to_bf16(result, rsign, rm);
}
