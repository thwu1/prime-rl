#include <stdio.h>

/* Test: irreducible flow with dead code elimination —
   three-way entry into loop body */
int test_irr_dce(int mode, int val) {
    int r = 0;

    if (mode == 1)
        goto B;
    if (mode == 2)
        goto C;

A:
    r += val;
    if (r > 100) goto done;
    goto B;

B:
    r += val * 2;
    if (r > 100) goto done;
    goto C;

C:
    r += val / 2;
    if (r > 100) goto done;
    goto A;

done:
    return r;
}

int main(void) {
    int r;

    r = test_irr_dce(0, 30);
    if (r != 105) { printf("FAIL: mode=0,val=30 got %d\n", r); return 1; }

    r = test_irr_dce(1, 40);
    if (r != 140) { printf("FAIL: mode=1,val=40 got %d\n", r); return 2; }

    r = test_irr_dce(2, 50);
    if (r != 175) { printf("FAIL: mode=2,val=50 got %d\n", r); return 3; }

    return 0;
}
