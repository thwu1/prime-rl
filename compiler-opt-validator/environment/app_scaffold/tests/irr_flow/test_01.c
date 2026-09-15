#include <stdio.h>

/* Test: irreducible control flow with constant propagation.
   Inspired by SuperTest TSPR4541.C — verifies optimizer handles
   irreducible CFGs correctly. */
int test_irreducible(int n) {
    int result = 0;
    int i = 0;

    if (n > 5)
        goto L2;

L1:
    result += i;
    i++;
    if (i >= n)
        goto done;
    goto L2;

L2:
    result += i * 2;
    i++;
    if (i >= n)
        goto done;
    goto L1;

done:
    return result;
}

int main(void) {
    int r;

    r = test_irreducible(0);
    if (r != 0) { printf("FAIL: n=0 got %d\n", r); return 1; }

    r = test_irreducible(1);
    if (r != 0) { printf("FAIL: n=1 got %d\n", r); return 2; }

    r = test_irreducible(4);
    if (r != 10) { printf("FAIL: n=4 got %d\n", r); return 3; }

    r = test_irreducible(6);
    if (r != 21) { printf("FAIL: n=6 got %d\n", r); return 4; }

    return 0;
}
