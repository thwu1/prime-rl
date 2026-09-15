/* Test: right shift operator — C99 6.5.7 */
#include "harness.h"

int main(void) {
    TEST_INIT("right shift C99 6.5.7");

    /* Unsigned right shift: well-defined, vacated bits filled with zeros */
    unsigned int u = 0x80000000u;
    TEST_VERIFY((u >> 1) == 0x40000000u);

    /* Positive signed right shift: well-defined */
    int pos = 16;
    TEST_VERIFY((pos >> 2) == 4);

    int pos2 = 255;
    TEST_VERIFY((pos2 >> 4) == 15);

    /* Implementation-defined: right shift of negative signed integer.
       C99 6.5.7p5: "If E1 has a signed type and a negative value,
       the resulting value is implementation-defined."
       This test assumes arithmetic (sign-extending) right shift,
       which is common on x86/ARM but NOT guaranteed by the standard.
       On a platform with logical right shift, -16 >> 2 would give
       a large positive value, not -4. */
    int neg = -16;
    int shifted = neg >> 2;
    TEST_VERIFY(shifted == -4);

    /* Another implementation-defined assumption: -1 >> n should give -1
       only with arithmetic shift. With logical shift, it would give
       (2^(32-n) - 1) or similar. */
    int neg2 = -1;
    TEST_VERIFY((neg2 >> 4) == -1);

    TEST_RESULT();
}
