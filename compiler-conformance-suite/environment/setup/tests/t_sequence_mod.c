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

    /* Undefined behavior: two unsequenced modifications of i.
       C99 6.5p2: "Between the previous and next sequence point an
       object shall have its stored value modified at most once by
       the evaluation of an expression."
       Both i++ sub-expressions modify i without an intervening
       sequence point. The result is undefined. */
    int i = 1;
    int result = i++ + i++;
    TEST_VERIFY(result == 2);

    /* Undefined behavior: unsequenced read and modification.
       C99 6.5p2: "Furthermore, the prior value shall be read only
       to determine the value to be stored."
       j is read (left operand) and modified (j++) without a
       sequence point between them. */
    int j = 5;
    int val = j + j++;
    TEST_VERIFY(val == 10);

    TEST_RESULT();
}
