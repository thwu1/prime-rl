#include <stdio.h>

/* Test: irreducible control flow with alternating accumulation paths — FIXED */
int test_irr_alt(int n) {
    int r = 0, i = 0;

    if (n % 2)
        goto B;

A:
    r += i * 3;
    i++;
    if (i >= n)
        goto end;
    goto B;

B:
    r += i + 1;
    i++;
    if (i >= n)
        goto end;
    goto A;

end:
    return r;
}

int main(void) {
    int r;

    r = test_irr_alt(3);
    if (r != 7) { printf("FAIL: n=3 got %d expected 7\n", r); return 1; }

    r = test_irr_alt(4);
    if (r != 12) { printf("FAIL: n=4 got %d expected 12\n", r); return 2; }

    r = test_irr_alt(5);
    if (r != 21) { printf("FAIL: n=5 got %d expected 21\n", r); return 3; }

    r = test_irr_alt(6);
    if (r != 30) { printf("FAIL: n=6 got %d expected 30\n", r); return 4; }

    return 0;
}
