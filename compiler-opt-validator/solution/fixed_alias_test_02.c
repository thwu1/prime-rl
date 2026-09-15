#include <stdio.h>
#include <string.h>

/* Aliasing test: write through one pointer, read through another — FIXED */
int test_alias_write(void) {
    int a = 10;
    int *p1 = &a;
    int *p2 = &a;

    *p1 = 20;
    *p2 += 5;

    return *p1;
}

/* Type punning via memcpy (well-defined, unlike pointer cast) */
unsigned int float_to_bits(float f) {
    unsigned int result;
    memcpy(&result, &f, sizeof(result));
    return result;
}

int main(void) {
    if (test_alias_write() != 25) {
        printf("FAIL: alias_write got %d\n", test_alias_write());
        return 1;
    }

    unsigned int bits = float_to_bits(1.0f);
    if (bits != 0x3f800000) {
        printf("FAIL: float_to_bits(1.0f) = 0x%x\n", bits);
        return 2;
    }

    return 0;
}
