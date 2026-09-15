/* Test: signed integer arithmetic — C99 6.5p5 */
#include "harness.h"
#include <limits.h>

static int increment_check(int x) {
    /* If signed overflow doesn't occur, x + 1 > x is always true.
       But if x == INT_MAX, x + 1 overflows: undefined behavior. */
    return (x + 1) > x;
}

int main(void) {
    TEST_INIT("signed overflow C99 6.5p5");

    /* Well-defined cases */
    TEST_VERIFY(increment_check(0) == 1);
    TEST_VERIFY(increment_check(-1) == 1);
    TEST_VERIFY(increment_check(100) == 1);
    TEST_VERIFY(increment_check(INT_MIN) == 1);

    /* INT_MAX + 1 is signed integer overflow: undefined behavior.
       C99 6.5p5: "If an exceptional condition occurs during the
       evaluation of an expression (that is, if the result is not
       mathematically defined or not in the range of representable
       values for its type), the behavior is undefined."
       At -O0: two's complement wrap gives INT_MIN, (INT_MIN > INT_MAX) → 0
       At -O2: compiler assumes no overflow, (x+1 > x) is always true → 1 */
    int (*volatile fn)(int) = increment_check;
    TEST_VERIFY(fn(INT_MAX) == 0);

    TEST_RESULT();
}
