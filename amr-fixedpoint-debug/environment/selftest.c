/*
 * Self-consistency tests for Q15/Q31 basic operations and DPF primitives.
 * Tests mathematical properties that correct implementations must satisfy.
 *
 */

#include <stdio.h>
#include "basicop.h"
#include "oper_32b.h"

static int tests_run  = 0;
static int tests_pass = 0;

#define CHECK(cond, msg) do { \
    tests_run++; \
    if (!(cond)) { printf("FAIL: %s\n", (msg)); } \
    else { tests_pass++; } \
} while (0)

/* 1. Additive identity: add(x,0)==x, sub(x,0)==x */
static void test_additive_identity(void)
{
    Word16 vals[] = {0, 1, -1, 100, -100, MAX_16, MIN_16, 16384, -16384};
    int i, ok = 1;
    for (i = 0; i < 9; i++) {
        if (add(vals[i], 0) != vals[i]) { ok = 0; break; }
        if (sub(vals[i], 0) != vals[i]) { ok = 0; break; }
    }
    CHECK(ok, "additive identity: add(x,0)==x, sub(x,0)==x");
}

/* 2. 16-bit saturation at arithmetic bounds */
static void test_saturation_bounds(void)
{
    int ok = 1;
    if (add(MAX_16, 1) != MAX_16) ok = 0;
    if (sub(MIN_16, 1) != MIN_16) ok = 0;
    if (add(MAX_16, MAX_16) != MAX_16) ok = 0;
    if (sub(MIN_16, MAX_16) != MIN_16) ok = 0;
    CHECK(ok, "16-bit saturation at bounds");
}

/* 3. L_mult: product of two same-sign operands must be positive */
static void test_L_mult_sign(void)
{
    Word32 r = L_mult((Word16)MIN_16, (Word16)MIN_16);
    CHECK(r > 0, "L_mult(-32768,-32768) must be positive");
}

/* 4. L_mult: 2*a*b for small non-overflowing values */
static void test_L_mult_small(void)
{
    int ok = 1;
    if (L_mult(100, 200) != 40000L) ok = 0;
    if (L_mult(-100, 200) != -40000L) ok = 0;
    if (L_mult(1, 1) != 2L) ok = 0;
    if (L_mult(0, 12345) != 0L) ok = 0;
    CHECK(ok, "L_mult small values: L_mult(a,b)==2*a*b");
}

/* 5. norm_l: L_shl(x, norm_l(x)) must land in [0x40000000, MAX_32] */
static void test_norm_l_range(void)
{
    Word32 vals[] = {1, 2, 255, 1024, 65536, 0x01000000L,
                     0x10000000L, 0x20000000L, 0x40000000L, MAX_32};
    int i, ok = 1;
    for (i = 0; i < 10; i++) {
        Word16 n = norm_l(vals[i]);
        Word32 s = L_shl(vals[i], n);
        if (s < (Word32)0x40000000L || s > MAX_32) { ok = 0; break; }
    }
    CHECK(ok, "norm_l: L_shl(x,norm_l(x)) in [0x40000000, MAX_32] for x>0");
}

/* 6. round_fx(L_deposit_h(x)) == x */
static void test_round_deposit_inverse(void)
{
    Word16 vals[] = {0, 1, -1, 100, -100, MAX_16, MIN_16, 4096};
    int i, ok = 1;
    for (i = 0; i < 8; i++) {
        if (round_fx(L_deposit_h(vals[i])) != vals[i]) { ok = 0; break; }
    }
    CHECK(ok, "round_fx(L_deposit_h(x)) == x");
}

/* 7. round_fx midpoint carry: rounding at the half boundary */
static void test_round_midpoint(void)
{
    Word16 r_at_mid  = round_fx((Word32)0x00008000L);
    Word16 r_at_zero = round_fx((Word32)0x00000000L);
    CHECK(r_at_mid == r_at_zero + 1,
          "round_fx: midpoint (lower=0x8000) carries to upper half");
}

/* 8. DPF round-trip: L_Comp(L_Extract(x)) preserves x within 1 LSB */
static void test_dpf_roundtrip(void)
{
    Word32 vals[] = {0, 100000, -100000, 0x12345678L, MAX_32 - 1};
    int i, ok = 1;
    for (i = 0; i < 5; i++) {
        Word16 hi, lo;
        Word32 r, d;
        L_Extract(vals[i], &hi, &lo);
        r = L_Comp(hi, lo);
        d = L_sub(vals[i], r);
        if (d < -1 || d > 1) { ok = 0; break; }
    }
    CHECK(ok, "DPF round-trip: L_Comp(L_Extract(x)) ~= x");
}

/* 9. Mpy_32 operand symmetry: Mpy_32(a,b,c,d) == Mpy_32(c,d,a,b) */
static void test_Mpy32_symmetry(void)
{
    Word32 r1 = Mpy_32(12000, 5000, 8000, 3000);
    Word32 r2 = Mpy_32(8000, 3000, 12000, 5000);
    CHECK(r1 == r2, "Mpy_32 operand symmetry: Mpy_32(a,b,c,d)==Mpy_32(c,d,a,b)");
}

/* 10. Mpy_32 cross-terms: both lo*hi products must contribute */
static void test_Mpy32_cross_terms(void)
{
    Word16 h1 = 10000, h2 = 8000, lv = 5000;
    Word32 base     = Mpy_32(h1, 0, h2, 0);
    Word32 with_lo2 = Mpy_32(h1, 0, h2, lv);
    Word32 with_lo1 = Mpy_32(h1, lv, h2, 0);
    Word32 d_lo2 = L_sub(with_lo2, base);
    Word32 d_lo1 = L_sub(with_lo1, base);
    CHECK(d_lo2 != 0 && d_lo1 != 0,
          "Mpy_32: both hi*lo cross-terms contribute to result");
}

int main(void)
{
    printf("=== Basic Operation Self-Consistency Tests ===\n\n");

    test_additive_identity();
    test_saturation_bounds();
    test_L_mult_sign();
    test_L_mult_small();
    test_norm_l_range();
    test_round_deposit_inverse();
    test_round_midpoint();
    test_dpf_roundtrip();
    test_Mpy32_symmetry();
    test_Mpy32_cross_terms();

    printf("\nResult: %d/%d passed\n", tests_pass, tests_run);
    if (tests_pass == tests_run) {
        printf("All checks passed.\n");
        return 0;
    }
    printf("%d check(s) FAILED.\n", tests_run - tests_pass);
    return 1;
}
