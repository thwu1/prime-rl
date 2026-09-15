#include <stdio.h>

/* Test: aliasing through pointer writes and reads */
int test_alias_write(void) {
    int a = 10;
    int *p1 = &a;
    int *p2 = &a;  /* p1 and p2 alias */

    *p1 = 20;
    *p2 += 5;

    return *p1;  /* should be 25 */
}

/* Type punning via pointer cast */
unsigned int float_to_bits(float f) {
    unsigned int *ip = (unsigned int *)&f;
    return *ip;
}

int main(void) {
    if (test_alias_write() != 25) {
        printf("FAIL: alias_write got %d\n", test_alias_write());
        return 1;
    }

    /* 1.0f = 0x3f800000 in IEEE 754 */
    unsigned int bits = float_to_bits(1.0f);
    if (bits != 0x3f000000) {
        printf("FAIL: float_to_bits(1.0f) = 0x%x\n", bits);
        return 2;
    }

    return 0;
}
