/* numparse.c -- Fast decimal-to-double parsing library
 *
 * Provides fast_parse_double() for converting ASCII decimal number strings
 * to IEEE 754 binary64 floating-point values.
 *
 * Design: optimistic fast path using exact precomputed powers of 10,
 * with a general-purpose fallback for cases outside the fast path range.
 *
 */

#include <stdint.h>
#include <string.h>
#include <math.h>
#include <float.h>

/* Powers of 10 exactly representable in IEEE 754 binary64.
 * 10^0 through 10^22 are exact; higher powers incur rounding. */
static const double kExactPow10[] = {
    1e0,  1e1,  1e2,  1e3,  1e4,  1e5,  1e6,  1e7,  1e8,  1e9,
    1e10, 1e11, 1e12, 1e13, 1e14, 1e15, 1e16, 1e17, 1e18, 1e19,
    1e20, 1e21, 1e22
};

/*
 * Convert a (mantissa, decimal_exponent) pair into a double.
 *
 * mantissa:  significand as unsigned 64-bit integer (up to 19 decimal digits)
 * dec_exp:   power-of-10 exponent (value = mantissa * 10^dec_exp)
 * negative:  1 if the original string had a leading minus sign
 * truncated: 1 if non-zero digits beyond the 19th were dropped
 */
static int assemble_double(uint64_t mantissa, int dec_exp, int negative,
                           int truncated, double *out) {

    /* ---- Zero mantissa ---- */
    if (mantissa == 0) {
        /* All parsed digits are zero; result is zero regardless of exponent.
         * Per IEEE 754, +0 and -0 compare equal and behave identically in
         * arithmetic, so we canonicalize to positive zero for consistency. */
        *out = 0.0;
        return 0;
    }

    /* ---- Clamp obviously out-of-range exponents ---- */
    if (dec_exp > 308) {
        *out = negative ? (-1.0 / 0.0) : (1.0 / 0.0);
        return 0;
    }
    /* DBL_MIN_10_EXP is -307; with an 18-digit mantissa the magnitude
     * falls below the representable range for exponents below -308. */
    if (dec_exp < -308) {
        *out = 0.0;
        return 0;
    }

    /* ---- Fast path: exact multiply ---- */
    if (mantissa < (1ULL << 53)) {
        double d = (double)mantissa;  /* exact: mantissa < 2^53 */

        if (dec_exp >= 0 && dec_exp <= 22) {
            d *= kExactPow10[dec_exp];
            if (negative) d = -d;
            *out = d;
            return 0;
        }
        if (dec_exp < 0 && dec_exp >= -22) {
            d /= kExactPow10[-dec_exp];
            if (negative) d = -d;
            *out = d;
            return 0;
        }
        /* Extended: split 10^e = 10^(e-22) * 10^22 when both factors exact */
        if (dec_exp > 22 && dec_exp <= 37) {
            double t = d * kExactPow10[dec_exp - 22];
            if (t <= 9007199254740991.0) {   /* intermediate still exact */
                t *= kExactPow10[22];
                if (negative) t = -t;
                *out = t;
                return 0;
            }
        }
    }

    /* ---- Slow path: general computation ---- */
    {
        double d = (double)mantissa;
        double p = pow(10.0, (double)dec_exp);
        d *= p;

        /* Subnormal results are unreliable with the pow()-based path
         * and carry severe performance penalties; flush them to zero. */
        if (d != 0.0 && fabs(d) < DBL_MIN) {
            d = 0.0;
        }

        if (negative) d = -d;
        *out = d;
        return 0;
    }
}

/*
 * Parse a decimal floating-point string into a double.
 *
 * Format:  [+-]? digits [. digits]? ([eE] [+-]? digits)?
 *
 * On success writes the result to *result and returns 0.
 * On syntax error returns -1 and leaves *result unchanged.
 */
int fast_parse_double(const char *str, int len, double *result) {
    if (!str || len <= 0 || !result) return -1;

    const char *p   = str;
    const char *end = str + len;

    /* ---- Sign ---- */
    int negative = 0;
    if (*p == '-')      { negative = 1; p++; }
    else if (*p == '+') { p++; }
    if (p >= end) return -1;

    /* ---- Integer and fractional digits ---- */
    uint64_t mantissa  = 0;
    int ndigits        = 0;
    int ndigits_stored = 0;
    int dot_pos        = -1;
    int truncated      = 0;
    int any_digit      = 0;

    while (p < end) {
        char c = *p;
        if (c >= '0' && c <= '9') {
            any_digit = 1;
            if (ndigits_stored < 19) {
                mantissa = mantissa * 10 + (unsigned)(c - '0');
                ndigits_stored++;
            } else {
                if (c != '0') truncated = 1;
            }
            ndigits++;
            p++;
        } else if (c == '.') {
            if (dot_pos >= 0) return -1;
            dot_pos = ndigits;
            p++;
        } else {
            break;
        }
    }
    if (!any_digit) return -1;

    /* Compute decimal exponent from fractional position */
    int dec_exp = 0;
    if (dot_pos >= 0)
        dec_exp = dot_pos - ndigits;
    if (ndigits > 19)
        dec_exp += (ndigits - 19);

    /* ---- Explicit exponent ---- */
    if (p < end && (*p == 'e' || *p == 'E')) {
        p++;
        if (p >= end) return -1;
        int exp_neg = 0;
        if (*p == '-')      { exp_neg = 1; p++; }
        else if (*p == '+') { p++; }
        if (p >= end || *p < '0' || *p > '9') return -1;

        int exp_val = 0;
        while (p < end && *p >= '0' && *p <= '9') {
            if (exp_val < 100000)
                exp_val = exp_val * 10 + (*p - '0');
            p++;
        }
        if (exp_neg) exp_val = -exp_val;
        dec_exp += exp_val;
    }

    return assemble_double(mantissa, dec_exp, negative, truncated, result);
}
