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
    /* BUG: sizeof did not evaluate x++, so x is still 5, not 6 */
    TEST_VERIFY(x == 6);

    /* sizeof applied to an expression determines the type */
    TEST_VERIFY(sizeof(1 + 1.0) == sizeof(double));
    TEST_VERIFY(sizeof('a') == sizeof(int));  /* char constant has type int in C */

    TEST_RESULT();
}
