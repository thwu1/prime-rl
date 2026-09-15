/* Test: C99 6.5.7 — Bitwise shift operators */
#include "harness.h"
#include <limits.h>

int main(void) {
    TEST_INIT("shift operators C99 6.5.7");

    /* basic left shift: 6 << 2 = 24 */
    int six = 6;
    int two = 2;
    TEST_VERIFY((six << two) == 24);

    /* unsigned left shift wraps modulo 2^N */
    unsigned int u = UINT_MAX;
    TEST_VERIFY((u << 1) == (UINT_MAX - 1));

    /* shift by 0 is identity */
    int x = 0x70F0;
    TEST_VERIFY((x << 0) == x);
    TEST_VERIFY((x >> 0) == x);

    /* right shift unsigned fills with zeros */
    unsigned int high = 0x80000000u;
    TEST_VERIFY((high >> 1) == 0x40000000u);

    /* left shift of 1 is multiplication by 2 (unsigned) */
    unsigned int val = 12345u;
    TEST_VERIFY((val << 1) == val * 2);

    TEST_RESULT();
}
