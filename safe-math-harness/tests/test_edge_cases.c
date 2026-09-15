/*
 * test_edge_cases.c - Direct edge-case tests for safe_math.h functions
 *
 * Tests every UB-sensitive edge case for int32_t arithmetic wrappers.
 * Returns 0 if all pass, non-zero (count of failures) otherwise.
 * Must be compiled with -I/app to find safe_math.h.
 *
 */

#include <stdio.h>
#include <stdint.h>
#include <limits.h>
#include "safe_math.h"

static int failures = 0;
static int total = 0;

#define EXPECT_EQ(expr, expected) do { \
    int32_t _r = (expr); \
    int32_t _e = (expected); \
    total++; \
    if (_r != _e) { \
        printf("FAIL [%d]: %s = %d, expected %d\n", total, #expr, (int)_r, (int)_e); \
        failures++; \
    } \
} while (0)

int main(void) {

    /* ===== safe_add_int32_t (should be correct) ===== */
    EXPECT_EQ(safe_add_int32_t(1, 2), 3);
    EXPECT_EQ(safe_add_int32_t(-1, -2), -3);
    EXPECT_EQ(safe_add_int32_t(INT32_MAX, 0), INT32_MAX);
    EXPECT_EQ(safe_add_int32_t(INT32_MIN, 0), INT32_MIN);
    EXPECT_EQ(safe_add_int32_t(INT32_MAX, 1), 0);     /* overflow */
    EXPECT_EQ(safe_add_int32_t(INT32_MIN, -1), 0);    /* underflow */
    EXPECT_EQ(safe_add_int32_t(INT32_MAX, INT32_MIN), -1);

    /* ===== safe_sub_int32_t ===== */
    EXPECT_EQ(safe_sub_int32_t(5, 3), 2);
    EXPECT_EQ(safe_sub_int32_t(-5, -3), -2);
    EXPECT_EQ(safe_sub_int32_t(INT32_MIN, 0), INT32_MIN);
    EXPECT_EQ(safe_sub_int32_t(INT32_MIN, 1), 0);         /* underflow */
    EXPECT_EQ(safe_sub_int32_t(INT32_MAX, -1), 0);        /* overflow */
    EXPECT_EQ(safe_sub_int32_t(0, INT32_MIN), 0);         /* overflow: 0 - INT32_MIN */
    EXPECT_EQ(safe_sub_int32_t(1, INT32_MIN), 0);         /* overflow */
    EXPECT_EQ(safe_sub_int32_t(-1, INT32_MIN), INT32_MAX); /* exact fit */
    EXPECT_EQ(safe_sub_int32_t(-2, INT32_MIN), INT32_MAX - 1);
    EXPECT_EQ(safe_sub_int32_t(INT32_MIN, INT32_MIN), 0);

    /* ===== safe_mul_int32_t ===== */
    EXPECT_EQ(safe_mul_int32_t(3, 4), 12);
    EXPECT_EQ(safe_mul_int32_t(-3, 4), -12);
    EXPECT_EQ(safe_mul_int32_t(-3, -4), 12);
    EXPECT_EQ(safe_mul_int32_t(0, INT32_MIN), 0);
    EXPECT_EQ(safe_mul_int32_t(INT32_MIN, 0), 0);
    EXPECT_EQ(safe_mul_int32_t(1, INT32_MIN), INT32_MIN);
    EXPECT_EQ(safe_mul_int32_t(INT32_MIN, 1), INT32_MIN);
    EXPECT_EQ(safe_mul_int32_t(-1, -1), 1);
    EXPECT_EQ(safe_mul_int32_t(INT32_MAX, 2), 0);         /* overflow */
    EXPECT_EQ(safe_mul_int32_t(INT32_MIN, 2), 0);         /* underflow */
    EXPECT_EQ(safe_mul_int32_t(INT32_MIN, -1), 0);        /* overflow */
    EXPECT_EQ(safe_mul_int32_t(46340, 46340), 2147395600); /* just under */
    EXPECT_EQ(safe_mul_int32_t(46341, 46341), 0);         /* just over */
    EXPECT_EQ(safe_mul_int32_t(-46340, 46340), -2147395600);
    EXPECT_EQ(safe_mul_int32_t(-46341, 46341), 0);        /* underflow */

    /* ===== safe_div_int32_t ===== */
    EXPECT_EQ(safe_div_int32_t(10, 2), 5);
    EXPECT_EQ(safe_div_int32_t(-10, 2), -5);
    EXPECT_EQ(safe_div_int32_t(10, -2), -5);
    EXPECT_EQ(safe_div_int32_t(10, 0), 0);                /* div by zero */
    EXPECT_EQ(safe_div_int32_t(0, 0), 0);
    EXPECT_EQ(safe_div_int32_t(INT32_MIN, -1), 0);        /* overflow */
    EXPECT_EQ(safe_div_int32_t(INT32_MIN, 1), INT32_MIN);
    EXPECT_EQ(safe_div_int32_t(INT32_MIN, 2), INT32_MIN / 2);
    EXPECT_EQ(safe_div_int32_t(-1, 1), -1);

    /* ===== safe_mod_int32_t ===== */
    EXPECT_EQ(safe_mod_int32_t(10, 3), 1);
    EXPECT_EQ(safe_mod_int32_t(-10, 3), -1);
    EXPECT_EQ(safe_mod_int32_t(10, 0), 0);                /* mod by zero */
    EXPECT_EQ(safe_mod_int32_t(0, 0), 0);
    EXPECT_EQ(safe_mod_int32_t(INT32_MIN, -1), 0);        /* overflow */
    EXPECT_EQ(safe_mod_int32_t(INT32_MIN, 2), 0);
    EXPECT_EQ(safe_mod_int32_t(INT32_MIN, INT32_MAX), -1);

    /* ===== safe_lshift_int32_t ===== */
    EXPECT_EQ(safe_lshift_int32_t(1, 0), 1);
    EXPECT_EQ(safe_lshift_int32_t(1, 3), 8);
    EXPECT_EQ(safe_lshift_int32_t(1, 30), 1073741824);    /* 2^30, fits */
    EXPECT_EQ(safe_lshift_int32_t(1073741823, 1), 2147483646); /* just fits */
    EXPECT_EQ(safe_lshift_int32_t(0, 15), 0);
    EXPECT_EQ(safe_lshift_int32_t(-1, 5), 0);             /* negative a */
    EXPECT_EQ(safe_lshift_int32_t(INT32_MIN, 0), 0);      /* negative a */
    EXPECT_EQ(safe_lshift_int32_t(1, 31), 0);             /* result overflows */
    EXPECT_EQ(safe_lshift_int32_t(INT32_MAX, 1), 0);      /* result overflows */
    EXPECT_EQ(safe_lshift_int32_t(1073741824, 1), 0);     /* result overflows */
    EXPECT_EQ(safe_lshift_int32_t(1, 32), 0);             /* shift too large */
    EXPECT_EQ(safe_lshift_int32_t(1, -1), 0);             /* negative shift */
    EXPECT_EQ(safe_lshift_int32_t(1, 100), 0);            /* way too large */

    /* ===== safe_rshift_int32_t (should be correct) ===== */
    EXPECT_EQ(safe_rshift_int32_t(8, 2), 2);
    EXPECT_EQ(safe_rshift_int32_t(1, 0), 1);
    EXPECT_EQ(safe_rshift_int32_t(INT32_MAX, 1), INT32_MAX / 2);
    EXPECT_EQ(safe_rshift_int32_t(1, 32), 0);             /* shift too large */
    EXPECT_EQ(safe_rshift_int32_t(1, -1), 0);             /* negative shift */
    EXPECT_EQ(safe_rshift_int32_t(0, 5), 0);

    /* ===== safe_neg_int32_t ===== */
    EXPECT_EQ(safe_neg_int32_t(5), -5);
    EXPECT_EQ(safe_neg_int32_t(-5), 5);
    EXPECT_EQ(safe_neg_int32_t(0), 0);
    EXPECT_EQ(safe_neg_int32_t(INT32_MAX), -INT32_MAX);
    EXPECT_EQ(safe_neg_int32_t(INT32_MIN), 0);            /* overflow */
    EXPECT_EQ(safe_neg_int32_t(1), -1);
    EXPECT_EQ(safe_neg_int32_t(-1), 1);

    /* === Summary === */
    if (failures == 0) {
        printf("ALL %d TESTS PASSED\n", total);
    } else {
        printf("FAILED: %d/%d tests failed\n", failures, total);
    }
    return failures;
}
