/* fp8_impl.c - Complete IEEE 754 compliant FP8 E4M3 arithmetic library.
 *
 * Uses exact integer arithmetic (int64_t mantissa * 2^exponent) for
 * intermediate computation, then applies IEEE 754 rounding to produce
 * the FP8 result. This ensures correct single-rounding for FMA.
 *
 */

#include "fp8_api.h"
#include <math.h>
#include <string.h>
#include <stdint.h>

/* ---- Field extraction ---- */
static inline int fp8s(uint8_t r) { return (r >> 7) & 1; }
static inline int fp8e(uint8_t r) { return (r >> 3) & 0xF; }
static inline int fp8m(uint8_t r) { return r & 0x7; }
static inline uint8_t fp8pack(int s, int e, int m) {
    return (uint8_t)((s << 7) | ((e & 0xF) << 3) | (m & 7));
}

/* ---- Special value constructors ---- */
static inline uint8_t fp8inf(int s) { return fp8pack(s, 15, 0); }
static inline uint8_t fp8nan(void) { return 0x79; }
static inline uint8_t fp8zero(int s) { return fp8pack(s, 0, 0); }
static inline uint8_t fp8max(int s) { return fp8pack(s, 14, 7); }

/* ---- Classify ---- */
int fp8_classify(uint8_t r) {
    int e = fp8e(r), m = fp8m(r);
    if (e == 15) return m ? FP8_CLASS_NAN : FP8_CLASS_INFINITY;
    if (e == 0) return m ? FP8_CLASS_SUBNORMAL : FP8_CLASS_ZERO;
    return FP8_CLASS_NORMAL;
}

/* ---- Decode to double ---- */
double fp8_to_float(uint8_t r) {
    int s = fp8s(r), e = fp8e(r), m = fp8m(r);
    if (e == 15) return m ? NAN : (s ? -INFINITY : INFINITY);
    if (e == 0 && m == 0) return s ? -0.0 : 0.0;
    double v;
    if (e == 0) v = ldexp((double)m, -9);       /* subnormal: m * 2^(-9) */
    else v = ldexp((double)(8 + m), e - 10);     /* normal: (8+m) * 2^(e-10) */
    return s ? -v : v;
}

/* ---- Overflow handler ---- */
static uint8_t overflow_result(int sign, int rnd) {
    if (rnd == FP8_RNE || rnd == FP8_RNA) return fp8inf(sign);
    if (rnd == FP8_RZ) return fp8max(sign);
    if (rnd == FP8_RU) return sign ? fp8max(sign) : fp8inf(sign);
    /* FP8_RD */ return sign ? fp8inf(sign) : fp8max(sign);
}

/* ---- Round exact value (mantissa * 2^exponent) to FP8 ---- */
static uint8_t round_to_fp8(int64_t mantissa, int exponent, int rnd) {
    if (mantissa == 0) return fp8zero(0);
    int sign = 0;
    uint64_t am;
    if (mantissa < 0) { sign = 1; am = (uint64_t)(-mantissa); }
    else { am = (uint64_t)mantissa; }

    /* Remove trailing zeros for canonical form */
    while (am > 1 && (am & 1) == 0) { am >>= 1; exponent++; }

    /* Find MSB position (0-indexed) */
    int msb = 0;
    { uint64_t t = am; while (t > 1) { t >>= 1; msb++; } }

    int eu = exponent + msb;        /* unbiased exponent */
    int emin = -6, emax = 7;

    if (eu > emax) return overflow_result(sign, rnd);

    if (eu >= emin) {
        /* ---- Normal ---- */
        int nbits = msb + 1;
        int need = 4;               /* 1 hidden + 3 mantissa */
        if (nbits <= need) {
            int m = (int)((am << (need - nbits)) & 7);
            return fp8pack(sign, eu + 7, m);
        }
        int extra = nbits - need;
        uint64_t tr = am >> extra;
        uint64_t rem = am & ((1ULL << extra) - 1);
        uint64_t half = 1ULL << (extra - 1);
        int up = 0;
        switch (rnd) {
            case FP8_RNE: up = (rem > half) || (rem == half && (tr & 1)); break;
            case FP8_RNA: up = (rem >= half); break;
            case FP8_RU:  up = (rem > 0 && !sign); break;
            case FP8_RD:  up = (rem > 0 && sign); break;
            default: break;
        }
        if (up) tr++;
        if (tr >= (1ULL << need)) {
            tr >>= 1; eu++;
            if (eu > emax) return overflow_result(sign, rnd);
        }
        return fp8pack(sign, eu + 7, (int)(tr & 7));
    }

    /* ---- Subnormal ---- */
    int shift = exponent - (emin - 3);   /* exponent - (-9) */
    if (shift >= 0) {
        uint64_t ms = am << shift;
        if (ms >= 8) return fp8pack(sign, 1, 0);
        if (ms == 0) return fp8zero(sign);
        return fp8pack(sign, 0, (int)ms);
    }
    int extra = -shift;
    if (extra >= 64) {
        if ((rnd == FP8_RU && !sign) || (rnd == FP8_RD && sign))
            return fp8pack(sign, 0, 1);
        return fp8zero(sign);
    }
    uint64_t ms = am >> extra;
    uint64_t rem = am & ((1ULL << extra) - 1);
    uint64_t half = 1ULL << (extra - 1);
    int up = 0;
    switch (rnd) {
        case FP8_RNE: up = (rem > half) || (rem == half && (ms & 1)); break;
        case FP8_RNA: up = (rem >= half); break;
        case FP8_RU:  up = (rem > 0 && !sign); break;
        case FP8_RD:  up = (rem > 0 && sign); break;
        default: break;
    }
    if (up) ms++;
    if (ms >= 8) return fp8pack(sign, 1, 0);
    if (ms == 0) return fp8zero(sign);
    return fp8pack(sign, 0, (int)ms);
}

/* ---- Encode double to FP8 ---- */
uint8_t fp8_from_float(double value, int rounding) {
    if (isnan(value)) return fp8nan();
    if (isinf(value)) return value < 0 ? fp8inf(1) : fp8inf(0);

    uint64_t bits;
    memcpy(&bits, &value, 8);
    int s = (int)((bits >> 63) & 1);
    int fe = (int)((bits >> 52) & 0x7FF);
    uint64_t fm = bits & 0xFFFFFFFFFFFFFULL;

    if (fe == 0 && fm == 0) return fp8zero(s);

    int64_t mant;
    int exp;
    if (fe == 0) { mant = (int64_t)fm; exp = 1 - 1023 - 52; }
    else { mant = (int64_t)((1ULL << 52) | fm); exp = fe - 1023 - 52; }
    if (s) mant = -mant;
    return round_to_fp8(mant, exp, rounding);
}

/* ---- Exact representation ---- */
typedef struct { int64_t m; int e; } exact_t;

static exact_t to_exact(uint8_t r) {
    int e = fp8e(r), m = fp8m(r), s = fp8s(r);
    exact_t x;
    if (e == 0) { x.m = m; x.e = -9; }
    else { x.m = 8 + m; x.e = e - 10; }
    if (s) x.m = -x.m;
    return x;
}

static uint8_t zero_sign(int rnd, int sa, int sb) {
    if (rnd == FP8_RD) return fp8zero(1);
    if (sa && sb) return fp8zero(1);
    return fp8zero(0);
}

/* ---- Addition ---- */
uint8_t fp8_add(uint8_t a, uint8_t b, int rounding) {
    int ac = fp8_classify(a), bc = fp8_classify(b);
    if (ac == FP8_CLASS_NAN || bc == FP8_CLASS_NAN) return fp8nan();
    if (ac == FP8_CLASS_INFINITY && bc == FP8_CLASS_INFINITY) {
        return (fp8s(a) != fp8s(b)) ? fp8nan() : a;
    }
    if (ac == FP8_CLASS_INFINITY) return a;
    if (bc == FP8_CLASS_INFINITY) return b;

    exact_t ea = to_exact(a), eb = to_exact(b);
    int64_t ma, mb; int re;
    if (ea.e >= eb.e) { ma = ea.m << (ea.e - eb.e); mb = eb.m; re = eb.e; }
    else { ma = ea.m; mb = eb.m << (eb.e - ea.e); re = ea.e; }
    int64_t rm = ma + mb;
    if (rm == 0) return zero_sign(rounding, fp8s(a), fp8s(b));
    return round_to_fp8(rm, re, rounding);
}

/* ---- Multiplication ---- */
uint8_t fp8_mul(uint8_t a, uint8_t b, int rounding) {
    int ac = fp8_classify(a), bc = fp8_classify(b);
    int rs = fp8s(a) ^ fp8s(b);
    if (ac == FP8_CLASS_NAN || bc == FP8_CLASS_NAN) return fp8nan();
    if ((ac == FP8_CLASS_INFINITY && bc == FP8_CLASS_ZERO) ||
        (ac == FP8_CLASS_ZERO && bc == FP8_CLASS_INFINITY)) return fp8nan();
    if (ac == FP8_CLASS_INFINITY || bc == FP8_CLASS_INFINITY) return fp8inf(rs);
    if (ac == FP8_CLASS_ZERO || bc == FP8_CLASS_ZERO) return fp8zero(rs);

    exact_t ea = to_exact(a), eb = to_exact(b);
    return round_to_fp8(ea.m * eb.m, ea.e + eb.e, rounding);
}

/* ---- Fused multiply-add ---- */
uint8_t fp8_fma(uint8_t a, uint8_t b, uint8_t c, int rounding) {
    int ac = fp8_classify(a), bc = fp8_classify(b), cc = fp8_classify(c);
    if (ac == FP8_CLASS_NAN || bc == FP8_CLASS_NAN || cc == FP8_CLASS_NAN)
        return fp8nan();
    if ((ac == FP8_CLASS_INFINITY && bc == FP8_CLASS_ZERO) ||
        (ac == FP8_CLASS_ZERO && bc == FP8_CLASS_INFINITY))
        return fp8nan();

    int ps = fp8s(a) ^ fp8s(b);
    if (ac == FP8_CLASS_INFINITY || bc == FP8_CLASS_INFINITY) {
        if (cc == FP8_CLASS_INFINITY && ps != fp8s(c)) return fp8nan();
        return fp8inf(ps);
    }
    if (cc == FP8_CLASS_INFINITY) return c;

    exact_t ea = to_exact(a), eb = to_exact(b), ec = to_exact(c);
    int64_t pm = ea.m * eb.m; int pe = ea.e + eb.e;
    int64_t cm = ec.m; int ce = ec.e;
    int64_t rm; int re;
    if (pe >= ce) { rm = (pm << (pe - ce)) + cm; re = ce; }
    else { rm = pm + (cm << (ce - pe)); re = pe; }
    if (rm == 0) return zero_sign(rounding, ps, fp8s(c));
    return round_to_fp8(rm, re, rounding);
}

/* ---- Compare ---- */
int fp8_compare(uint8_t a, uint8_t b) {
    if (fp8_classify(a) == FP8_CLASS_NAN || fp8_classify(b) == FP8_CLASS_NAN)
        return FP8_CMP_UNORDERED;
    if (fp8_classify(a) == FP8_CLASS_ZERO && fp8_classify(b) == FP8_CLASS_ZERO)
        return 0;

    int ac = fp8_classify(a), bc = fp8_classify(b);
    if (ac == FP8_CLASS_INFINITY && bc == FP8_CLASS_INFINITY) {
        if (fp8s(a) == fp8s(b)) return 0;
        return fp8s(a) ? -1 : 1;
    }
    if (ac == FP8_CLASS_INFINITY) return fp8s(a) ? -1 : 1;
    if (bc == FP8_CLASS_INFINITY) return fp8s(b) ? 1 : -1;

    exact_t ea = to_exact(a), eb = to_exact(b);
    int64_t ma, mb;
    if (ea.e >= eb.e) { ma = ea.m << (ea.e - eb.e); mb = eb.m; }
    else { ma = ea.m; mb = eb.m << (eb.e - ea.e); }
    if (ma < mb) return -1;
    if (ma > mb) return 1;
    return 0;
}
