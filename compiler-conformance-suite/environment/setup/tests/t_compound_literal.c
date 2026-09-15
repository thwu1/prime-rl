/* Test: C99 6.5.2.5 — Compound literals */
#include "harness.h"

int main(void) {
    TEST_INIT("compound literals C99 6.5.2.5");

    /* sizeof compound literal with incomplete array type */
    TEST_VERIFY(sizeof((int[]){1, 2, 3, 4}) == 4 * sizeof(int));
    TEST_VERIFY(sizeof((char[]){1, 2, 3}) == 3 * sizeof(char));
    TEST_VERIFY(sizeof((double[]){1.0, 2.0}) == 2 * sizeof(double));

    /* compound literal is an lvalue */
    int *p = (int[]){10, 20, 30};
    TEST_VERIFY(p[0] == 10);
    TEST_VERIFY(p[1] == 20);
    TEST_VERIFY(p[2] == 30);

    /* modifiable lvalue */
    p[0] = 99;
    TEST_VERIFY(p[0] == 99);

    TEST_RESULT();
}
