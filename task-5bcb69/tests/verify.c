
/*
 * Exhaustive verification program for cr_cbrtf.
 * Compares the implementation against MPFR for millions of test inputs
 * spanning the full float domain including subnormals.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>
#include <mpfr.h>
#include "cbrtf.h"

typedef union { float f; uint32_t u; } fu;

static mpfr_t g_mpfr;
static int g_mpfr_inited = 0;

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

    if (!g_mpfr_inited) {
        mpfr_init2(g_mpfr, 80);
        g_mpfr_inited = 1;
    }

    mpfr_set_flt(g_mpfr, x, MPFR_RNDN);
    mpfr_cbrt(g_mpfr, g_mpfr, MPFR_RNDN);
    float ret = mpfr_get_flt(g_mpfr, MPFR_RNDN);
    return ret;
}

static int g_total = 0;
static int g_failures = 0;
static int g_printed = 0;
static const int MAX_PRINT = 25;

static void check(float x) {
    g_total++;
    float got = cr_cbrtf(x);
    float expected = ref_cbrtf(x);
    fu g = {.f = got}, e = {.f = expected};

    if (isnan(expected) && isnan(got)) return;
    if (isnan(expected) || isnan(got)) {
        g_failures++;
        if (g_printed < MAX_PRINT) {
            fu xi = {.f = x};
            printf("FAIL: cbrtf(%a [0x%08x]) = %a [0x%08x], expected %a [0x%08x]\n",
                   x, xi.u, got, g.u, expected, e.u);
            g_printed++;
        }
        return;
    }

    if (g.u != e.u) {
        g_failures++;
        if (g_printed < MAX_PRINT) {
            fu xi = {.f = x};
            printf("FAIL: cbrtf(%a [0x%08x]) = %a [0x%08x], expected %a [0x%08x]\n",
                   x, xi.u, got, g.u, expected, e.u);
            g_printed++;
        }
    }
}

int main(void) {
    printf("=== cr_cbrtf exhaustive verification ===\n\n");

    /* --- Group 1: Special values --- */
    printf("  [1/9] Special values...\n");
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

    /* --- Group 2: Perfect cubes and reciprocals --- */
    printf("  [2/9] Perfect cubes...\n");
    {
        float vals[] = {1, -1, 8, -8, 27, -27, 64, -64, 125, -125,
                        216, -216, 343, -343, 512, -512, 729, -729,
                        1000, -1000, 1728, -1728, 4096, -4096,
                        0.125f, -0.125f, 0.015625f, -0.015625f,
                        0.001f, -0.001f, 0.000125f, -0.000125f,
                        1e10f, -1e10f, 1e20f, -1e20f, 1e30f, -1e30f,
                        1e-10f, -1e-10f, 1e-20f, -1e-20f, 1e-30f, -1e-30f};
        for (int i = 0; i < (int)(sizeof(vals)/sizeof(vals[0])); i++)
            check(vals[i]);
    }

    /* --- Group 3: Powers of 2 (range reduction boundaries) --- */
    printf("  [3/9] Powers of 2...\n");
    for (int e = -149; e <= 127; e++) {
        float x;
        if (e < -126) {
            fu u = {.u = 1u << (e + 149)};
            x = u.f;
        } else {
            fu u = {.u = (uint32_t)(e + 127) << 23};
            x = u.f;
        }
        check(x);
        check(-x);
    }

    /* --- Group 4: Near perfect cubes --- */
    printf("  [4/9] Near perfect cubes...\n");
    {
        float bases[] = {1, 8, 27, 64, 125, 216, 343, 512, 729, 1000, 1728, 4096};
        for (int i = 0; i < (int)(sizeof(bases)/sizeof(bases[0])); i++) {
            fu base = {.f = bases[i]};
            for (int delta = -200; delta <= 200; delta++) {
                int32_t bits = (int32_t)base.u + delta;
                if (bits <= 0) continue;
                fu u = {.u = (uint32_t)bits};
                if ((u.u & 0x7f800000u) == 0x7f800000u) continue;
                check(u.f);
                u.u |= 0x80000000u;
                check(u.f);
            }
        }
    }

    /* --- Group 5: Sampled subnormals --- */
    printf("  [5/9] Sampled subnormals...\n");
    for (uint32_t bits = 1; bits < 0x00800000u; bits += 31) {
        fu u = {.u = bits};
        check(u.f);
        u.u |= 0x80000000u;
        check(u.f);
    }

    /* --- Group 6: Random inputs (1M) --- */
    printf("  [6/9] Random inputs (1M)...\n");
    {
        uint32_t seed = 0xDEADBEEFu;
        for (int i = 0; i < 1000000; i++) {
            /* xorshift32 */
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            fu u = {.u = seed};
            if ((u.u & 0x7f800000u) == 0x7f800000u) continue;
            check(u.f);
        }
    }

    /* --- Group 7: Exhaustive [1.0, 2.0) --- */
    printf("  [7/9] Exhaustive [1.0, 2.0)...\n");
    for (uint32_t bits = 0x3F800000u; bits < 0x40000000u; bits++) {
        fu u = {.u = bits};
        check(u.f);
    }

    /* --- Group 8: Exhaustive [0.5, 1.0) --- */
    printf("  [8/9] Exhaustive [0.5, 1.0)...\n");
    for (uint32_t bits = 0x3F000000u; bits < 0x3F800000u; bits++) {
        fu u = {.u = bits};
        check(u.f);
    }

    /* --- Group 9: Exhaustive [2.0, 4.0) --- */
    printf("  [9/9] Exhaustive [2.0, 4.0)...\n");
    for (uint32_t bits = 0x40000000u; bits < 0x40800000u; bits++) {
        fu u = {.u = bits};
        check(u.f);
    }

    /* --- Summary --- */
    printf("\n");
    if (g_failures == 0) {
        printf("ALL TESTS PASSED (%d tests)\n", g_total);
    } else {
        printf("FAILED: %d/%d tests failed\n", g_failures, g_total);
    }

    if (g_mpfr_inited)
        mpfr_clear(g_mpfr);

    return g_failures > 0 ? 1 : 0;
}
