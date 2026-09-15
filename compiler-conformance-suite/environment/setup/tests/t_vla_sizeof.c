/* Test: C99 6.7.5.2 — Variable length arrays */
#include "harness.h"

static void test_vla(int n) {
    int vla[n];
    TEST_VERIFY(sizeof(vla) == (size_t)n * sizeof(int));
}

int main(void) {
    TEST_INIT("VLA sizeof C99 6.7.5.2");

    test_vla(1);
    test_vla(5);
    test_vla(100);

    /* VLA in a block scope */
    for (int i = 1; i <= 10; i++) {
        int arr[i];
        TEST_VERIFY(sizeof(arr) == (size_t)i * sizeof(int));
    }

    TEST_RESULT();
}
