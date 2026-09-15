/* Test: C99 6.7.2.1 — Flexible array members */
#include "harness.h"
#include <stdlib.h>
#include <string.h>

struct flex_array {
    int count;
    int data[];
};

int main(void) {
    TEST_INIT("flexible array members C99 6.7.2.1");

    /* sizeof struct with flexible array does not include the array */
    TEST_VERIFY(sizeof(struct flex_array) >= sizeof(int));

    /* allocate and use flexible array */
    int n = 5;
    struct flex_array *fa = malloc(sizeof(struct flex_array) + (size_t)n * sizeof(int));
    TEST_VERIFY(fa != NULL);

    fa->count = n;
    for (int i = 0; i < n; i++)
        fa->data[i] = i * 10;

    TEST_VERIFY(fa->count == 5);
    TEST_VERIFY(fa->data[0] == 0);
    TEST_VERIFY(fa->data[2] == 20);
    TEST_VERIFY(fa->data[4] == 40);

    /* copy using memcpy */
    struct flex_array *fb = malloc(sizeof(struct flex_array) + (size_t)n * sizeof(int));
    TEST_VERIFY(fb != NULL);
    memcpy(fb, fa, sizeof(struct flex_array) + (size_t)n * sizeof(int));
    TEST_VERIFY(fb->count == 5);
    TEST_VERIFY(fb->data[3] == 30);

    free(fa);
    free(fb);

    TEST_RESULT();
}
