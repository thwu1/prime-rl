/*
 * LPC analysis pipeline — reads autocorrelation in DPF, outputs LP
 * coefficients via Levinson-Durbin.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include "basicop.h"
#include "oper_32b.h"
#include "levinson.h"

int main(void)
{
    Word16 Rh[M_LPC + 1], Rl[M_LPC + 1];
    Word16 A[M_LPC + 1];
    Word16 rc[4];
    LevinsonState *st = NULL;
    int i, rh, rl;

    for (i = 0; i <= M_LPC; i++) {
        if (scanf("%d %d", &rh, &rl) != 2) {
            fprintf(stderr, "Error: expected %d pairs of Rh Rl values\n",
                    M_LPC + 1);
            return 1;
        }
        Rh[i] = (Word16)rh;
        Rl[i] = (Word16)rl;
    }

    if (Levinson_init(&st) != 0) {
        fprintf(stderr, "Levinson_init failed\n");
        return 1;
    }

    Levinson(st, Rh, Rl, A, rc);

    for (i = 0; i <= M_LPC; i++)
        printf("%d\n", (int)A[i]);
    for (i = 0; i < 4; i++)
        printf("%d\n", (int)rc[i]);

    Levinson_exit(&st);
    return 0;
}
