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
       18 stored in 4-bit unsigned: 18 mod 16 = 2 */
    bf.c = 18;
    /* BUG: 18 does not fit in 4-bit unsigned. 18 % 16 = 2 */
    TEST_VERIFY(bf.c == 18);

    /* 1-bit unsigned: 2 mod 2 = 0 */
    bf.d = 2;
    TEST_VERIFY(bf.d == 0);

    TEST_RESULT();
}
