
/*
 * spot_check.c — Tests cr_cbrtf against MPFR for a sample of inputs.
 *
 * Coverage: special values, perfect cubes, exhaustive sweep of the
 * binade [1.0, 2.0), and random normal-range inputs.
 *
 * NOTE: subnormal inputs are not included in this spot check due to
 * CI performance constraints — subnormal verification is deferred to
 * the full integration test suite.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>
#include <mpfr.h>
#include "cbrtf.h"

typedef union { float f; uint32_t u; } fu;

static mpfr_t g_mp;
static int g_mp_init = 0;

static float ref_cbrtf(float x) {
    fu xi = {.f = x};
    uint32_t ax = xi.u & 0x7fffffffu;

    /* +-0 */
    if (ax == 0) return x;
    /* +-Inf */
    if (ax == 0x7f800000u) return x;
    /* NaN: return a quiet NaN preserving sign */
    if (ax > 0x7f800000u) {
        fu r = {.u = (xi.u & 0x80000000u) | 0x7fc00000u};
        return r.f;
    }

    if (!g_mp_init) {
        mpfr_init2(g_mp, 80);
        g_mp_init = 1;
    }

    mpfr_set_flt(g_mp, x, MPFR_RNDN);
    mpfr_cbrt(g_mp, g_mp, MPFR_RNDN);
    return mpfr_get_flt(g_mp, MPFR_RNDN);
}

static int g_total = 0;
static int g_fail = 0;
static int g_printed = 0;
static const int MAX_PRINT = 25;

static void check(float x) {
    g_total++;
    float got = cr_cbrtf(x);
    float expected = ref_cbrtf(x);
    fu g = {.f = got}, e = {.f = expected};

    if (isnan(expected) && isnan(got)) return;
    if (isnan(expected) || isnan(got)) goto fail;

    if (g.u != e.u) {
fail:
        g_fail++;
        if (g_printed < MAX_PRINT) {
            fu xi = {.f = x};
            int ulp_err = (int)g.u - (int)e.u;
            if (ulp_err < 0) ulp_err = -ulp_err;
            printf("  FAIL: cbrtf(%a [0x%08x]) = %a [0x%08x], "
                   "expected %a [0x%08x] (%d ULP)\n",
                   x, xi.u, got, g.u, expected, e.u, ulp_err);
            g_printed++;
        }
    }
}

int main(void) {
    int section_start, section_fail_start;

    printf("=== cr_cbrtf spot check (normal range) ===\n\n");

    /* --- Section 1: Special values --- */
    printf("[1/4] Special values...\n");
    section_start = g_total;
    section_fail_start = g_fail;
    check(0.0f);
    check(-0.0f);
    {
        volatile float inf = 1.0f / 0.0f;
        check(inf);
        check(-inf);
    }
    {
        volatile float nan_val = 0.0f / 0.0f;
        check(nan_val);
    }
    printf("  %d tested, %d failures\n\n",
           g_total - section_start, g_fail - section_fail_start);

    /* --- Section 2: Perfect cubes and reciprocals --- */
    printf("[2/4] Perfect cubes and reciprocals...\n");
    section_start = g_total;
    section_fail_start = g_fail;
    g_printed = 0;
    {
        float vals[] = {
            1, -1, 8, -8, 27, -27, 64, -64, 125, -125,
            216, -216, 343, -343, 512, -512, 729, -729,
            1000, -1000, 1728, -1728, 4096, -4096,
            0.125f, -0.125f, 0.015625f, -0.015625f,
            1e10f, -1e10f, 1e20f, -1e20f, 1e30f, -1e30f,
            1e-10f, -1e-10f, 1e-20f, -1e-20f
        };
        for (int i = 0; i < (int)(sizeof(vals) / sizeof(vals[0])); i++)
            check(vals[i]);
    }
    printf("  %d tested, %d failures\n\n",
           g_total - section_start, g_fail - section_fail_start);

    /* --- Section 3: Exhaustive sweep [1.0, 2.0) --- */
    printf("[3/4] Exhaustive sweep [1.0, 2.0) — 8388608 inputs...\n");
    section_start = g_total;
    section_fail_start = g_fail;
    g_printed = 0;
    for (uint32_t bits = 0x3F800000u; bits < 0x40000000u; bits++) {
        fu u = {.u = bits};
        check(u.f);
    }
    printf("  %d tested, %d failures\n\n",
           g_total - section_start, g_fail - section_fail_start);

    /* --- Section 4: Random normal-range inputs --- */
    printf("[4/4] Random normal-range inputs (50000)...\n");
    section_start = g_total;
    section_fail_start = g_fail;
    g_printed = 0;
    {
        uint32_t seed = 0xDEADBEEFu;
        for (int i = 0; i < 50000; i++) {
            /* xorshift32 */
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            /* Normal range only: biased exponent 1..254 */
            uint32_t bits = 0x00800000u + (seed % 0x7F000000u);
            if (i & 1) bits |= 0x80000000u;
            fu u = {.u = bits};
            check(u.f);
        }
    }
    printf("  %d tested, %d failures\n\n",
           g_total - section_start, g_fail - section_fail_start);

    /* --- Summary --- */
    printf("=== SUMMARY: %d of %d tests %s",
           g_total - g_fail, g_total,
           g_fail == 0 ? "PASSED" : "FAILED");
    if (g_fail > 0)
        printf(" (%d failures)", g_fail);
    printf(" ===\n");

    if (g_mp_init) mpfr_clear(g_mp);
    return g_fail > 0 ? 1 : 0;
}
