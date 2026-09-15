/* Test: C99 6.7.8 — Designated initializers */
#include "harness.h"

int main(void) {
    TEST_INIT("designated initializers C99 6.7.8");

    /* array designated initializer: unspecified elements are zero */
    int arr[5] = {[2] = 42, [4] = 99};
    TEST_VERIFY(arr[0] == 0);
    TEST_VERIFY(arr[1] == 0);
    TEST_VERIFY(arr[2] == 42);
    TEST_VERIFY(arr[3] == 0);
    TEST_VERIFY(arr[4] == 99);

    /* struct designated initializer with out-of-order fields */
    struct point { int x; int y; int z; };
    struct point p = {.z = 30, .x = 10};
    TEST_VERIFY(p.x == 10);
    TEST_VERIFY(p.y == 0);
    TEST_VERIFY(p.z == 30);

    /* nested designated initializer */
    struct { struct point p; int w; } s = {.p = {.x = 1, .y = 2}, .w = 3};
    TEST_VERIFY(s.p.x == 1);
    TEST_VERIFY(s.p.y == 2);
    TEST_VERIFY(s.p.z == 0);
    TEST_VERIFY(s.w == 3);

    /* array with mix of designated and positional */
    int mixed[4] = {1, [2] = 3, 4};
    TEST_VERIFY(mixed[0] == 1);
    TEST_VERIFY(mixed[1] == 0);
    TEST_VERIFY(mixed[2] == 3);
    TEST_VERIFY(mixed[3] == 4);

    TEST_RESULT();
}
