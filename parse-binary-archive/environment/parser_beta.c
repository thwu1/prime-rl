/* parser_beta.c -- Fast decimal-to-double: optimistic fast path + strtod() fallback
 *
 * Strategy: exact powers-of-10 table for the fast path with extended range,
 * delegating to the C library's strtod() for correctly-rounded results on
 * inputs outside the fast path.
 *
 */

#include <stdint.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include <stdlib.h>
#include <stdio.h>

/* Powers of 10 exactly representable in IEEE 754 binary64. */
static const double kExactPow10[] = {
    1e0,  1e1,  1e2,  1e3,  1e4,  1e5,  1e6,  1e7,  1e8,  1e9,
    1e10, 1e11, 1e12, 1e13, 1e14, 1e15, 1e16, 1e17, 1e18, 1e19,
    1e20, 1e21, 1e22
};

static int assemble_double(uint64_t mantissa, int dec_exp, int negative,
                           int truncated, double *out) {

    /* ---- Zero mantissa ---- */
    if (mantissa == 0) {
        *out = negative ? -0.0 : 0.0;
        return 0;
    }

    /* ---- Clamp obviously out-of-range exponents ---- */
    if (dec_exp > 308) {
        *out = negative ? (-1.0 / 0.0) : (1.0 / 0.0);
        return 0;
    }
    /* A 19-digit mantissa (up to ~10^18) with exponent -342 yields ~10^-324,
     * which is still a valid subnormal (smallest positive is ~5e-324). */
    if (dec_exp < -342) {
        *out = negative ? -0.0 : 0.0;
        return 0;
    }

    /* ---- Fast path: exact multiply ---- */
    if (mantissa < (1ULL << 53)) {
        double d = (double)mantissa;

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
        /* Extended positive: split 10^e into two exact factors */
        if (dec_exp > 22 && dec_exp <= 37) {
            double t = d * kExactPow10[dec_exp - 21];
            if (t <= 9007199254740991.0) {
                t *= kExactPow10[22];
                if (negative) t = -t;
                *out = t;
                return 0;
            }
        }
    }

    /* ---- Slow path: strtod() for correctly-rounded results ---- */
    {
        char buf[64];
        int n = snprintf(buf, sizeof(buf), "%llu", (unsigned long long)mantissa);
        snprintf(buf + n, sizeof(buf) - n, "e%d", dec_exp);
        double d = strtod(buf, NULL);
        if (negative) d = -d;
        *out = d;
        return 0;
    }
}

int fast_parse_double(const char *str, int len, double *result) {
    if (!str || len <= 0 || !result) return -1;

    const char *p   = str;
    const char *end = str + len;

    int negative = 0;
    if (*p == '-')      { negative = 1; p++; }
    else if (*p == '+') { p++; }
    if (p >= end) return -1;

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

    int dec_exp = 0;
    if (dot_pos >= 0)
        dec_exp = dot_pos - ndigits;
    if (ndigits > 19)
        dec_exp += (ndigits - 19);

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
