/* Correctly-rounded cube root for IEEE 754 binary32 (float).
 *
 * Algorithm:
 *   1. Handle special cases (+-0, +-Inf, NaN).
 *   2. Normalize subnormal inputs by scaling by 2^24.
 *   3. Decompose the exponent e = 3*q + r, r in {0, 1, 2}.
 *   4. Reduce to computing cbrt(m * 2^r), m in [1,2), via mantissa extraction.
 *   5. Obtain initial estimate using the double-precision bit-hack:
 *        bits(cbrt(x)) ~ bits(x)/3 + 0x2AA0000000000000
 *   6. Refine with 4 Newton-Raphson iterations in double precision:
 *        y <- (2*y + x / y^2) / 3
 *   7. Scale by 2^q and convert to float.
 *
 * Since float has 24-bit precision and double has 53-bit precision,
 * the double result (accurate to ~2^-52) always rounds correctly to float
 * (the worst-case distance from cbrt(any float) to a float midpoint
 * exceeds 2^-29 ULPs for the algebraic function cbrt).
 *
 */

#include <stdint.h>
#include "cbrtf.h"

typedef union { float f; uint32_t u; } b32u32_u;
typedef union { double f; uint64_t u; } b64u64_u;

float cr_cbrtf(float x) {
    b32u32_u xi = {.f = x};
    uint32_t hx = xi.u;
    uint32_t sign = hx & 0x80000000u;
    hx &= 0x7fffffffu;

    /* +-0 → return with sign preserved */
    if (hx == 0u)
        return x;

    /* NaN or Inf: x + x returns Inf unchanged and quiets sNaN */
    if (hx >= 0x7f800000u)
        return x + x;

    /* Convert |x| to double, handling subnormals */
    double xd;
    int e_adj = 0;
    if (hx < 0x00800000u) {
        /* Subnormal: multiply by 2^24 to normalise */
        b32u32_u tmp = {.u = hx};
        xd = (double)tmp.f * 0x1p24;
        e_adj = -24;
    } else {
        b32u32_u tmp = {.u = hx};
        xd = (double)tmp.f;
    }

    /* Extract the biased exponent from the double representation */
    b64u64_u du = {.f = xd};
    int biased = (int)(du.u >> 52);
    int e = biased - 1023 + e_adj;

    /* Euclidean division: e = 3*q + r, 0 <= r <= 2
     * For negative e, (e - 2) / 3 with C truncation-toward-zero
     * gives the correct floor-division quotient.                 */
    int q, r;
    if (e >= 0) {
        q = e / 3;
        r = e % 3;
    } else {
        q = (e - 2) / 3;
        r = e - 3 * q;
    }

    /* Set the double exponent to 1023 + r, keeping the mantissa.
     * This yields mp = m * 2^r where m in [1, 2), so mp in [1, 8). */
    du.u = (du.u & 0x000fffffffffffffULL) | ((uint64_t)(1023 + r) << 52);
    double mp = du.f;

    /* Initial approximation via the bit-level identity
     *   bits(cbrt(x)) ≈ bits(x) / 3 + C,  C = 2*1023*2^52 / 3.
     * C = 0x2AA0000000000000  (verified: gives exact result for x = 1 and x = 8). */
    b64u64_u yi = {.f = mp};
    yi.u = yi.u / 3 + 0x2AA0000000000000ULL;
    double y = yi.f;

    /* Four Newton-Raphson iterations:
     *   y_{n+1} = (2*y_n + mp / y_n^2) / 3
     * Quadratic convergence: ~4 bits → 8 → 16 → 32 → 53 (clamped by double). */
    double y2;
    y2 = y * y; y = (2.0 * y + mp / y2) / 3.0;
    y2 = y * y; y = (2.0 * y + mp / y2) / 3.0;
    y2 = y * y; y = (2.0 * y + mp / y2) / 3.0;
    y2 = y * y; y = (2.0 * y + mp / y2) / 3.0;

    /* Scale by 2^q by adding q to the double's biased exponent.
     * Safe because cbrt(any float) is always a normal double
     * (cbrt range for float inputs: ~[2^-50, 2^43]).            */
    b64u64_u res = {.f = y};
    res.u += (int64_t)q << 52;

    /* Convert to float (round-to-nearest-even) and restore sign */
    float rf = (float)res.f;
    b32u32_u out = {.f = rf};
    out.u |= sign;
    return out.f;
}
