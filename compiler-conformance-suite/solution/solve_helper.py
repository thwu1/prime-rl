#!/usr/bin/env python3

"""
Solution for compiler conformance UB analysis task.

This script:
1. Diagnoses all 7 defective tests across 3 categories
2. Fixes each test using the appropriate strategy
3. Writes 3 new conformance tests
4. Compiles and runs all 15 tests with gcc/clang at -O0/-O2/-O3
5. Generates /app/analysis.json
"""

import json
import os
import subprocess
import sys

TESTS_DIR = "/app/tests"


# ============================================================
# STEP 1: Fix wrong_expectation tests (3)
# ============================================================

def fix_integer_promotion():
    """Fix t_integer_promotion.c: (x + y) == 0 should be == 65536.

    C99 6.3.1.1: unsigned short operands are promoted to int before addition.
    The expression (x + y) has type int with value 65536.
    Truncation only occurs on assignment to unsigned short, not in comparison.
    """
    path = os.path.join(TESTS_DIR, "t_integer_promotion.c")

    fixed_src = """\
/* Test: C99 6.3.1.1 — Integer promotions */
#include "harness.h"
#include <limits.h>

int main(void) {
    TEST_INIT("integer promotions C99 6.3.1.1");

    /* Test 1: unsigned char promoted to int for arithmetic */
    unsigned char a = 200, b = 100;
    TEST_VERIFY((a - b) == 100);

    /* Test 2: unsigned short addition — stored result truncates */
    unsigned short x = 0xFFFF;
    unsigned short y = 0x0001;
    unsigned short stored = x + y;
    /* x and y are promoted to int: 65535 + 1 = 65536.
       Storing back to unsigned short: 65536 % 65536 = 0 */
    TEST_VERIFY(stored == 0);

    /* Test 3: unsigned short promoted expression (NOT stored back)
       FIXED: x and y are promoted to int before addition.
       The expression (x + y) has type int and value 65536.
       It is NOT truncated because no conversion to unsigned short occurs
       in the comparison — the comparison is performed in int. */
    TEST_VERIFY((x + y) == 65536);

    /* Test 4: signed/unsigned comparison — signed value converts
       to unsigned, so -1 becomes UINT_MAX which is > 1 */
    signed int neg = -1;
    unsigned int u = 1;
    TEST_VERIFY((unsigned int)neg > u);

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_integer_promotion.c",
        "category": "wrong_expectation",
        "description": (
            "Assertion (x + y) == 0 is incorrect. Both unsigned short operands "
            "are promoted to int before addition per C99 6.3.1.1. The expression "
            "(x + y) has type int and value 65536. Truncation to unsigned short "
            "only occurs on assignment, not in the comparison expression."
        ),
        "standard_ref": "C99 6.3.1.1 (Integer promotions)",
        "fix_applied": "Changed expected value from 0 to 65536 to match integer promotion rules."
    }


def fix_sizeof_expr():
    """Fix t_sizeof_expr.c: x == 6 should be x == 5.

    C99 6.5.3.4p2: sizeof does not evaluate its operand for non-VLA types.
    After sizeof(x++), x remains 5 because x++ is never evaluated.
    """
    path = os.path.join(TESTS_DIR, "t_sizeof_expr.c")

    fixed_src = """\
/* Test: C99 6.5.3.4 — The sizeof operator */
#include "harness.h"

int main(void) {
    TEST_INIT("sizeof operator C99 6.5.3.4");

    /* sizeof(char) is always 1 by definition */
    TEST_VERIFY(sizeof(char) == 1);

    /* size ordering guaranteed by the standard */
    TEST_VERIFY(sizeof(short) <= sizeof(int));
    TEST_VERIFY(sizeof(int) <= sizeof(long));
    TEST_VERIFY(sizeof(long) <= sizeof(long long));

    /* sizeof does NOT evaluate its operand (for non-VLA types)
       C99 6.5.3.4p2: "If the type of the operand is not a variable
       length array type, the operand is not evaluated" */
    int x = 5;
    size_t s = sizeof(x++);
    TEST_VERIFY(s == sizeof(int));
    /* FIXED: sizeof does not evaluate x++ (non-VLA), so x remains 5 */
    TEST_VERIFY(x == 5);

    /* sizeof applied to an expression determines the type */
    TEST_VERIFY(sizeof(1 + 1.0) == sizeof(double));
    TEST_VERIFY(sizeof('a') == sizeof(int));  /* char constant has type int in C */

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_sizeof_expr.c",
        "category": "wrong_expectation",
        "description": (
            "Assertion x == 6 after sizeof(x++) is incorrect. Per C99 6.5.3.4 "
            "paragraph 2, sizeof does not evaluate its operand when the type is "
            "not a variable length array. The x++ side effect never executes, "
            "so x remains 5."
        ),
        "standard_ref": "C99 6.5.3.4 (The sizeof operator)",
        "fix_applied": "Changed expected value from x == 6 to x == 5."
    }


def fix_bitfield_width():
    """Fix t_bitfield_width.c: bf.c == 18 should be bf.c == 2.

    C99 6.3.1.3p2: storing 18 in a 4-bit unsigned bit-field truncates
    modulo 2^4 = 16. 18 mod 16 = 2.
    """
    path = os.path.join(TESTS_DIR, "t_bitfield_width.c")

    fixed_src = """\
/* Test: C99 6.7.2.1 — Bit-field widths and value ranges */
#include "harness.h"

struct bits {
    signed int a : 3;    /* range: -4 to 3 */
    signed int b : 5;    /* range: -16 to 15 */
    unsigned int c : 4;  /* range: 0 to 15 */
    unsigned int d : 1;  /* range: 0 to 1 */
};

int main(void) {
    TEST_INIT("bit-field widths C99 6.7.2.1");

    struct bits bf;

    /* values within range */
    bf.a = 3;
    TEST_VERIFY(bf.a == 3);

    bf.a = -4;
    TEST_VERIFY(bf.a == -4);

    bf.b = -16;
    TEST_VERIFY(bf.b == -16);

    bf.b = 15;
    TEST_VERIFY(bf.b == 15);

    bf.c = 15;
    TEST_VERIFY(bf.c == 15);

    bf.d = 1;
    TEST_VERIFY(bf.d == 1);

    /* storing value outside unsigned range: truncation modulo 2^N
       C99 6.3.1.3p2: for unsigned, value is reduced modulo 2^N.
       FIXED: 18 stored in 4-bit unsigned truncates to 18 mod 16 = 2 */
    bf.c = 18;
    TEST_VERIFY(bf.c == 2);

    /* 1-bit unsigned: 2 mod 2 = 0 */
    bf.d = 2;
    TEST_VERIFY(bf.d == 0);

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_bitfield_width.c",
        "category": "wrong_expectation",
        "description": (
            "Assertion bf.c == 18 is incorrect. The 4-bit unsigned bit-field "
            "can only hold values 0-15. Per C99 6.3.1.3 paragraph 2, storing 18 "
            "into an unsigned type reduces it modulo 2^N where N is the bit width: "
            "18 mod 16 = 2."
        ),
        "standard_ref": "C99 6.7.2.1 / 6.3.1.3 (Bit-fields / Unsigned conversion)",
        "fix_applied": "Changed expected value from 18 to 2 to match modular truncation."
    }


# ============================================================
# STEP 2: Fix undefined_behavior tests (3)
# ============================================================

def fix_strict_alias():
    """Fix t_strict_alias.c: replace aliased pointer cast with memcpy.

    C99 6.5p7: An object shall have its stored value accessed only by an
    lvalue expression of a compatible type. The original test accesses int
    storage through a float pointer, violating strict aliasing.
    Fix: use memcpy for type punning, which is well-defined.
    """
    path = os.path.join(TESTS_DIR, "t_strict_alias.c")

    fixed_src = """\
/* Test: type punning (well-defined) — C99 6.5p7 */
#include "harness.h"
#include <string.h>
#include <stdint.h>

int main(void) {
    TEST_INIT("type punning via memcpy C99 6.5p7");

    /* FIXED: Use memcpy for type punning instead of pointer cast.
       memcpy does not violate strict aliasing because it operates
       on character types, which are permitted to alias any type. */

    /* float to uint32_t via memcpy */
    float f_val = 1.0f;
    uint32_t f_bits;
    memcpy(&f_bits, &f_val, sizeof(f_bits));
    TEST_VERIFY(f_bits == 0x3F800000u);  /* IEEE 754 encoding of 1.0f */

    /* uint32_t to float via memcpy */
    uint32_t known_bits = 0x42280000u;  /* IEEE 754 encoding of 42.0f */
    float f_result;
    memcpy(&f_result, &known_bits, sizeof(f_result));
    TEST_VERIFY(f_result == 42.0f);

    /* Round-trip: float -> bits -> float preserves value */
    float orig = -3.14f;
    uint32_t rt_bits;
    memcpy(&rt_bits, &orig, sizeof(rt_bits));
    float rt_copy;
    memcpy(&rt_copy, &rt_bits, sizeof(rt_copy));
    TEST_VERIFY(rt_copy == orig);

    /* Verify memcpy-based pun gives same result as direct store */
    int int_val = 42;
    int int_readback;
    memcpy(&int_readback, &int_val, sizeof(int_readback));
    TEST_VERIFY(int_readback == 42);

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_strict_alias.c",
        "category": "undefined_behavior",
        "description": (
            "Original test passes aliased int* and float* pointers to a function, "
            "violating the strict aliasing rule (C99 6.5p7). The function writes "
            "through float* and reads back through int*; at -O2 with TBAA the "
            "compiler assumes these don't alias and returns a stale cached value. "
            "The test passes at -O0 but fails at -O2."
        ),
        "standard_ref": "C99 6.5p7 (Strict aliasing rule)",
        "fix_applied": (
            "Replaced pointer-cast type punning with memcpy-based type punning. "
            "memcpy operates through character types which may alias any type per "
            "6.5p7, making it well-defined. Removed the aliased function call entirely."
        )
    }


def fix_signed_wrap():
    """Fix t_signed_wrap.c: replace overflow-dependent check with INT_MAX comparison.

    C99 6.5p5: signed integer overflow is undefined behavior. The original test
    relies on two's complement wrap-around for INT_MAX + 1, which compilers
    can optimize away at -O2.
    Fix: check against INT_MAX before addition.
    """
    path = os.path.join(TESTS_DIR, "t_signed_wrap.c")

    fixed_src = """\
/* Test: signed integer bounds checking — C99 6.5p5 */
#include "harness.h"
#include <limits.h>

/* FIXED: Check whether increment would overflow BEFORE performing it.
   The original used (x + 1) > x which is UB when x == INT_MAX because
   x + 1 overflows. Compilers at -O2 assume no signed overflow and
   optimize (x + 1) > x to always-true. */
static int increment_safe(int x) {
    /* Well-defined: compare against INT_MAX without computing x + 1 */
    return (x < INT_MAX) ? 1 : 0;
}

int main(void) {
    TEST_INIT("signed integer bounds C99 6.5p5");

    /* Normal cases: increment is safe */
    TEST_VERIFY(increment_safe(0) == 1);
    TEST_VERIFY(increment_safe(-1) == 1);
    TEST_VERIFY(increment_safe(100) == 1);
    TEST_VERIFY(increment_safe(INT_MIN) == 1);

    /* INT_MAX: increment would overflow, so result is 0 */
    TEST_VERIFY(increment_safe(INT_MAX) == 0);

    /* Verify boundary: INT_MAX - 1 is safe to increment */
    TEST_VERIFY(increment_safe(INT_MAX - 1) == 1);

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_signed_wrap.c",
        "category": "undefined_behavior",
        "description": (
            "Original test uses (x + 1) > x to check for overflow. When x == INT_MAX, "
            "x + 1 is signed integer overflow (C99 6.5p5: undefined behavior). At -O0, "
            "two's complement wrap gives INT_MIN and the comparison returns 0. At -O2, "
            "the compiler assumes no signed overflow, deduces x + 1 > x is always true, "
            "and returns 1. The test expects 0 but gets 1 at -O2."
        ),
        "standard_ref": "C99 6.5p5 (Undefined behavior: overflow)",
        "fix_applied": (
            "Replaced (x + 1) > x with (x < INT_MAX) ? 1 : 0 to avoid computing the "
            "potentially overflowing x + 1. The comparison against INT_MAX is well-defined "
            "and gives the correct result at all optimization levels."
        )
    }


def fix_sequence_mod():
    """Fix t_sequence_mod.c: sequence operations to eliminate UB.

    C99 6.5p2: Between consecutive sequence points, an object shall have
    its stored value modified at most once. The original test modifies i
    twice and reads j while modifying it, both UB.
    Fix: use separate statements with sequence points between modifications.
    """
    path = os.path.join(TESTS_DIR, "t_sequence_mod.c")

    fixed_src = """\
/* Test: expression evaluation order — C99 6.5p2 */
#include "harness.h"

int main(void) {
    TEST_INIT("sequence points C99 6.5p2");

    /* Well-defined: each modification in a separate statement */
    int a = 1;
    a++;
    int b = a;
    a++;
    int c = a;
    TEST_VERIFY(b == 2);
    TEST_VERIFY(c == 3);

    /* Well-defined: comma operator provides a sequence point */
    int d = 0;
    d++, d++, d++;
    TEST_VERIFY(d == 3);

    /* FIXED: Eliminated double-modification UB — the original expression
       modified i twice between sequence points (C99 6.5p2). Each
       post-increment is now in its own statement. */
    int i = 1;
    int r1 = i++;   /* r1 = 1, i becomes 2; sequence point at ; */
    int r2 = i++;   /* r2 = 2, i becomes 3; sequence point at ; */
    int result = r1 + r2;
    TEST_VERIFY(result == 3);  /* 1 + 2 = 3 */

    /* FIXED: Eliminated unsequenced read-modify UB — the original
       expression read and modified j without an intervening sequence
       point (C99 6.5p2). Read and modification are now separate. */
    int j = 5;
    int j_before = j;   /* read j: 5; sequence point */
    j++;                 /* modify j: becomes 6; sequence point */
    int val = j_before + j;
    TEST_VERIFY(val == 11);  /* 5 + 6 = 11 */

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_sequence_mod.c",
        "category": "undefined_behavior",
        "description": (
            "Two sequence point violations: (1) double post-increment modifies i "
            "twice between sequence points, violating C99 6.5p2; (2) reading j for "
            "the addition while post-incrementing j modifies it, also without an "
            "intervening sequence point. Both produce undefined behavior — different "
            "compilers and optimization levels may yield different results."
        ),
        "standard_ref": "C99 6.5p2 (Sequence points)",
        "fix_applied": (
            "Separated each modification into its own statement, inserting "
            "sequence points (statement boundaries) between reads and writes. "
            "For the double-increment: evaluate each increment in a separate statement. "
            "For the read-modify: read j first, then increment in next statement."
        )
    }


# ============================================================
# STEP 3: Fix implementation_defined test (1)
# ============================================================

def fix_neg_rshift():
    """Fix t_neg_rshift.c: make right shift of negative values portable.

    C99 6.5.7p5: right shift of negative signed integer is implementation-defined.
    The original test assumes arithmetic (sign-extending) right shift.
    Fix: use unsigned right shift with explicit sign extension.
    """
    path = os.path.join(TESTS_DIR, "t_neg_rshift.c")

    fixed_src = """\
/* Test: right shift operator — C99 6.5.7 */
#include "harness.h"
#include <limits.h>

/* Portable arithmetic right shift: well-defined for all values.
   Uses unsigned shift (always fills with zeros) then applies sign extension
   explicitly, avoiding the implementation-defined behavior of C99 6.5.7p5. */
static int portable_arith_rshift(int val, unsigned int n) {
    if (val >= 0) {
        return val >> n;   /* well-defined for non-negative values */
    }
    /* Negative: convert to unsigned, shift, then set sign bits */
    unsigned int uval = (unsigned int)val;
    unsigned int shifted = uval >> n;
    /* Create mask for sign extension: set the top n bits */
    unsigned int sign_bits = ~(~0u >> n);
    return (int)(shifted | sign_bits);
}

int main(void) {
    TEST_INIT("right shift (portable) C99 6.5.7");

    /* Unsigned right shift: well-defined, vacated bits filled with zeros */
    unsigned int u = 0x80000000u;
    TEST_VERIFY((u >> 1) == 0x40000000u);

    /* Positive signed right shift: well-defined */
    int pos = 16;
    TEST_VERIFY((pos >> 2) == 4);

    int pos2 = 255;
    TEST_VERIFY((pos2 >> 4) == 15);

    /* FIXED: Use portable_arith_rshift instead of direct >> on negative values.
       The original relied on implementation-defined behavior (C99 6.5.7p5).
       This portable version uses unsigned shift + explicit sign extension. */
    TEST_VERIFY(portable_arith_rshift(-16, 2) == -4);
    TEST_VERIFY(portable_arith_rshift(-1, 4) == -1);
    TEST_VERIFY(portable_arith_rshift(-256, 3) == -32);

    /* Verify portable version matches for non-negative inputs */
    TEST_VERIFY(portable_arith_rshift(16, 2) == 4);
    TEST_VERIFY(portable_arith_rshift(0, 5) == 0);

    TEST_RESULT();
}
"""

    with open(path, "w") as f:
        f.write(fixed_src)

    return {
        "file": "t_neg_rshift.c",
        "category": "implementation_defined",
        "description": (
            "Right shift of negative signed integers is implementation-defined per "
            "C99 6.5.7p5: 'If E1 has a signed type and a negative value, the resulting "
            "value is implementation-defined.' The test assumes arithmetic (sign-extending) "
            "right shift, which is common on x86 but not guaranteed. On platforms with "
            "logical right shift, -16 >> 2 would give a large positive value, not -4."
        ),
        "standard_ref": "C99 6.5.7p5 (Implementation-defined right shift)",
        "fix_applied": (
            "Replaced direct >> on negative values with a portable_arith_rshift() "
            "function that converts to unsigned, performs unsigned right shift "
            "(well-defined: fills with zeros), then explicitly sets sign-extension "
            "bits. This gives arithmetic right shift semantics portably."
        )
    }


# ============================================================
# STEP 4: Write three new conformance tests
# ============================================================

def write_new_tests():
    """Write the three tests required by /app/new_tests.txt."""

    tests = {}

    # --- t_irreducible_flow.c: Irreducible control flow graph ---
    tests["t_irreducible_flow.c"] = """\
/* Test: irreducible control flow and optimizer correctness */
#include "harness.h"

/* Function with an irreducible control flow graph.
   The loop formed by bb2->bb12->bb2 and bb4->bb12->bb4 has two entry
   points (bb2 and bb4), making it irreducible. This tests that the
   optimizer correctly handles constant propagation and dead code
   elimination through the irreducible structure.
   Inspired by SuperTest TSPR4541 methodology. */
static int irreducible(int j, int k, int recurs) {
    int x = 0;
    int result = 0;

    if (recurs) {
        irreducible(0, 0, 0);  /* prevent inlining */
    }

bb2:
    if (j == 0) {
        x = 1;
        goto bb12;
    } else {
bb4:
        if (k == 0) {
            goto bb13;
        } else {
            k = 0;
            goto bb12;
        }
    }

bb12:
    if (x == 0) {
        result = 20;
        goto bb2;
    } else {
        result = 10;
        goto bb4;
    }

bb13:
    return result;
}

int main(void) {
    TEST_INIT("irreducible control flow optimization");

    /* j=1,k=1: enters at bb2, goes to bb4 (k!=0), k=0, bb12 (x==0),
       result=20, bb2 (j!=0), bb4 (k==0), bb13 -> returns 20 */
    TEST_VERIFY(irreducible(1, 1, 0) == 20);

    /* j=0,k=1: enters at bb2, x=1, bb12 (x!=0), result=10,
       bb4 (k!=0), k=0, bb12 (x!=0), result=10, bb4 (k==0), bb13 -> 10 */
    TEST_VERIFY(irreducible(0, 1, 0) == 10);

    /* j=1,k=0: enters at bb2, goes to bb4 (k==0), bb13 -> returns 0 */
    TEST_VERIFY(irreducible(1, 0, 0) == 0);

    /* j=0,k=0: enters at bb2, x=1, bb12 (x!=0), result=10,
       bb4 (k==0), bb13 -> returns 10 */
    TEST_VERIFY(irreducible(0, 0, 0) == 10);

    TEST_RESULT();
}
"""

    # --- t_union_pun.c: Union-based type punning ---
    tests["t_union_pun.c"] = """\
/* Test: union type punning — C99 TC3 footnote 82 */
#include "harness.h"
#include <stdint.h>

int main(void) {
    TEST_INIT("union type punning C99 TC3");

    /* Type punning through unions is well-defined per C99 TC3 footnote 82:
       "If the member used to read the contents of a union object is not
       the same as the member last used to store a value in the object,
       the appropriate part of the object representation of the value is
       reinterpreted as an object representation in the new type." */

    /* float -> uint32_t: verify IEEE 754 bit pattern */
    union { float f; uint32_t u; } fu;
    fu.f = 1.0f;
    TEST_VERIFY(fu.u == 0x3F800000u);  /* IEEE 754: 1.0f */

    /* uint32_t -> float */
    fu.u = 0x40000000u;
    TEST_VERIFY(fu.f == 2.0f);  /* IEEE 754: 2.0f */

    fu.u = 0x42280000u;
    TEST_VERIFY(fu.f == 42.0f);  /* IEEE 754: 42.0f */

    /* double -> uint64_t: verify IEEE 754 bit pattern */
    union { double d; uint64_t u; } du;
    du.d = 1.0;
    TEST_VERIFY(du.u == 0x3FF0000000000000ULL);  /* IEEE 754: 1.0 */

    /* uint64_t -> double */
    du.u = 0x4000000000000000ULL;
    TEST_VERIFY(du.d == 2.0);  /* IEEE 754: 2.0 */

    /* Round-trip: float -> uint32_t -> float preserves exact value */
    float pi_f = 3.14159265f;
    union { float f; uint32_t u; } roundtrip;
    roundtrip.f = pi_f;
    uint32_t pi_bits = roundtrip.u;
    roundtrip.u = pi_bits;
    TEST_VERIFY(roundtrip.f == pi_f);  /* exact equality: no precision loss */

    /* Round-trip: double -> uint64_t -> double */
    double pi_d = 3.141592653589793;
    union { double d; uint64_t u; } rt_d;
    rt_d.d = pi_d;
    uint64_t pi_d_bits = rt_d.u;
    rt_d.u = pi_d_bits;
    TEST_VERIFY(rt_d.d == pi_d);

    /* Negative zero has a distinct bit pattern */
    fu.f = -0.0f;
    TEST_VERIFY(fu.u == 0x80000000u);  /* sign bit set, rest zero */
    TEST_VERIFY(fu.f == 0.0f);  /* -0.0f == 0.0f in C */

    TEST_RESULT();
}
"""

    # --- t_restrict_qual.c: restrict qualifier ---
    tests["t_restrict_qual.c"] = """\
/* Test: restrict qualifier — C99 6.7.3.1 */
#include "harness.h"

/* With restrict, the compiler can assume dst and src don't overlap,
   enabling vectorization and avoiding redundant loads of *src
   after writes to *dst. */
static void add_scaled(int * restrict dst, const int * restrict src,
                        int scale, int n) {
    for (int i = 0; i < n; i++) {
        dst[i] = src[i] * scale + src[i];
    }
}

/* restrict on output: compiler can assume out doesn't alias a or b */
static void vec_add(int * restrict out,
                    const int * restrict a,
                    const int * restrict b, int n) {
    for (int i = 0; i < n; i++) {
        out[i] = a[i] + b[i];
    }
}

/* Accumulator with restrict: sum doesn't alias the array */
static void accumulate(int * restrict sum,
                       const int * restrict arr, int n) {
    *sum = 0;
    for (int i = 0; i < n; i++) {
        *sum += arr[i];
    }
}

int main(void) {
    TEST_INIT("restrict qualifier C99 6.7.3.1");

    /* Test add_scaled with non-overlapping arrays */
    int src[4] = {1, 2, 3, 4};
    int dst[4];
    add_scaled(dst, src, 2, 4);
    TEST_VERIFY(dst[0] == 3);   /* 1*2 + 1 = 3 */
    TEST_VERIFY(dst[1] == 6);   /* 2*2 + 2 = 6 */
    TEST_VERIFY(dst[2] == 9);   /* 3*2 + 3 = 9 */
    TEST_VERIFY(dst[3] == 12);  /* 4*2 + 4 = 12 */

    /* Test vec_add */
    int a[3] = {10, 20, 30};
    int b[3] = {1, 2, 3};
    int out[3];
    vec_add(out, a, b, 3);
    TEST_VERIFY(out[0] == 11);
    TEST_VERIFY(out[1] == 22);
    TEST_VERIFY(out[2] == 33);

    /* Test accumulate */
    int arr[5] = {1, 2, 3, 4, 5};
    int total;
    accumulate(&total, arr, 5);
    TEST_VERIFY(total == 15);

    /* Verify with larger values */
    int big[3] = {1000000, 2000000, 3000000};
    int big_sum;
    accumulate(&big_sum, big, 3);
    TEST_VERIFY(big_sum == 6000000);

    TEST_RESULT();
}
"""

    for name, content in tests.items():
        path = os.path.join(TESTS_DIR, name)
        with open(path, "w") as f:
            f.write(content)
        print(f"  Wrote {path}")


# ============================================================
# STEP 5: Compile and run all tests
# ============================================================

ALL_TEST_FILES = [
    "t_compound_literal.c",
    "t_shift_ops.c",
    "t_designated_init.c",
    "t_vla_sizeof.c",
    "t_flexible_array.c",
    "t_integer_promotion.c",
    "t_sizeof_expr.c",
    "t_bitfield_width.c",
    "t_strict_alias.c",
    "t_signed_wrap.c",
    "t_sequence_mod.c",
    "t_neg_rshift.c",
    "t_irreducible_flow.c",
    "t_union_pun.c",
    "t_restrict_qual.c",
]


def compile_and_run_test(test_file, compiler, opt_level):
    """Compile and run a single test. Returns ('pass'|'fail', message)."""
    src = os.path.join(TESTS_DIR, test_file)
    base = test_file.replace(".c", "")
    binary = f"/tmp/test_{base}_{compiler}_{opt_level.replace('-', '')}"

    compile_result = subprocess.run(
        [compiler, opt_level, "-std=c11", "-I/app", "-o", binary, src, "-lm"],
        capture_output=True, text=True, timeout=30
    )
    if compile_result.returncode != 0:
        return "fail", f"compile error: {compile_result.stderr[:300]}"

    try:
        run_result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
    finally:
        if os.path.exists(binary):
            os.remove(binary)

    if run_result.returncode != 0:
        return "fail", f"runtime failure: {run_result.stdout.strip()}"

    if "PASS" in run_result.stdout:
        return "pass", ""
    else:
        return "fail", f"no PASS: {run_result.stdout.strip()}"


def run_all_tests():
    """Run all tests with all compiler/opt combinations."""
    compilers = ["gcc", "clang"]
    opt_levels = ["-O0", "-O2", "-O3"]

    results = {}
    total_pass = 0
    total_fail = 0

    for test in ALL_TEST_FILES:
        test_results = {}
        for compiler in compilers:
            for opt in opt_levels:
                key = f"{compiler}_{opt.replace('-', '')}"
                status, msg = compile_and_run_test(test, compiler, opt)
                test_results[key] = status
                if status == "pass":
                    total_pass += 1
                    print(f"  PASS: {test} {compiler} {opt}")
                else:
                    total_fail += 1
                    print(f"  FAIL: {test} {compiler} {opt}: {msg}")
        results[test] = test_results

    print(f"\n  Total: {total_pass} passed, {total_fail} failed")
    return results


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Step 1: Fixing wrong_expectation tests")
    print("=" * 60)
    defects = []
    defects.append(fix_integer_promotion())
    print(f"  Fixed: {defects[-1]['file']}")
    defects.append(fix_sizeof_expr())
    print(f"  Fixed: {defects[-1]['file']}")
    defects.append(fix_bitfield_width())
    print(f"  Fixed: {defects[-1]['file']}")

    print()
    print("=" * 60)
    print("Step 2: Fixing undefined_behavior tests")
    print("=" * 60)
    defects.append(fix_strict_alias())
    print(f"  Fixed: {defects[-1]['file']}")
    defects.append(fix_signed_wrap())
    print(f"  Fixed: {defects[-1]['file']}")
    defects.append(fix_sequence_mod())
    print(f"  Fixed: {defects[-1]['file']}")

    print()
    print("=" * 60)
    print("Step 3: Fixing implementation_defined tests")
    print("=" * 60)
    defects.append(fix_neg_rshift())
    print(f"  Fixed: {defects[-1]['file']}")

    print()
    print("=" * 60)
    print("Step 4: Writing new conformance tests")
    print("=" * 60)
    write_new_tests()

    print()
    print("=" * 60)
    print("Step 5: Running all tests")
    print("=" * 60)
    results = run_all_tests()

    print()
    print("=" * 60)
    print("Step 6: Generating analysis report")
    print("=" * 60)
    report = {
        "defects": defects,
        "all_results": results
    }

    report_path = "/app/analysis.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report written to {report_path}")

    failures = sum(
        1 for t in results.values()
        for s in t.values()
        if s == "fail"
    )
    if failures > 0:
        print(f"\nWARNING: {failures} test failure(s)!")
        return 1

    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
