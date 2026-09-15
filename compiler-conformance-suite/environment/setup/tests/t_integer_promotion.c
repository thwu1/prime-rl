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
       BUG: x and y are promoted to int before addition.
       The expression (x + y) has type int and value 65536.
       It is NOT truncated because no conversion to unsigned short occurs
       in the comparison — the comparison is performed in int. */
    TEST_VERIFY((x + y) == 0);

    /* Test 4: signed/unsigned comparison — signed value converts
       to unsigned, so -1 becomes UINT_MAX which is > 1 */
    signed int neg = -1;
    unsigned int u = 1;
    TEST_VERIFY((unsigned int)neg > u);

    TEST_RESULT();
}
