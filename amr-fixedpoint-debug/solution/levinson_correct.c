/*
 * Levinson-Durbin algorithm — correct double-precision fixed-point
 * implementation following 3GPP TS 26.073.
 *
 */

#include <stdlib.h>
#include <stdio.h>
#include "basicop.h"
#include "oper_32b.h"
#include "levinson.h"

int Levinson_init(LevinsonState **state)
{
    LevinsonState *s;
    if (state == NULL) return -1;
    s = (LevinsonState *)malloc(sizeof(LevinsonState));
    if (s == NULL) return -1;
    Levinson_reset(s);
    *state = s;
    return 0;
}

int Levinson_reset(LevinsonState *state)
{
    int i;
    if (state == NULL) return -1;
    state->old_A[0] = 4096;
    for (i = 1; i <= M_LPC; i++)
        state->old_A[i] = 0;
    return 0;
}

void Levinson_exit(LevinsonState **state)
{
    if (state == NULL || *state == NULL) return;
    free(*state);
    *state = NULL;
}

int Levinson(LevinsonState *st,
             Word16 Rh[], Word16 Rl[],
             Word16 A[],  Word16 rc[])
{
    Word16 i, j;
    Word16 hi, lo;
    Word16 Kh, Kl;
    Word16 alp_h, alp_l, alp_exp;
    Word16 Ah[M_LPC + 1], Al[M_LPC + 1];
    Word16 Anh[M_LPC + 1], Anl[M_LPC + 1];
    Word32 t0, t1, t2;

    /* K = A[1] = -R[1] / R[0] */
    t1 = L_Comp(Rh[1], Rl[1]);
    t2 = L_abs(t1);
    t0 = Div_32(t2, Rh[0], Rl[0]);
    if (t1 > 0)
        t0 = L_negate(t0);
    L_Extract(t0, &Kh, &Kl);

    rc[0] = round_fx(t0);

    t0 = L_shr(t0, 4);
    L_Extract(t0, &Ah[1], &Al[1]);

    /* Alpha = R[0] * (1 - K^2) */
    t0 = Mpy_32(Kh, Kl, Kh, Kl);
    t0 = L_abs(t0);
    t0 = L_sub((Word32)0x7fffffffL, t0);
    L_Extract(t0, &hi, &lo);
    t0 = Mpy_32(Rh[0], Rl[0], hi, lo);

    /* Normalize Alpha */
    alp_exp = norm_l(t0);
    t0 = L_shl(t0, alp_exp);
    L_Extract(t0, &alp_h, &alp_l);

    /* Iterations i = 2 to M_LPC */
    for (i = 2; i <= M_LPC; i++) {
        /* t0 = SUM(R[j]*A[i-j], j=1..i-1) + R[i] */
        t0 = 0;
        for (j = 1; j < i; j++) {
            t0 = L_add(t0, Mpy_32(Rh[j], Rl[j], Ah[i - j], Al[i - j]));
        }
        t0 = L_shl(t0, 4);

        t1 = L_Comp(Rh[i], Rl[i]);
        t0 = L_add(t0, t1);

        /* K = -t0 / Alpha */
        t1 = L_abs(t0);
        t2 = Div_32(t1, alp_h, alp_l);
        if (t0 > 0)
            t2 = L_negate(t2);
        t2 = L_shl(t2, alp_exp);
        L_Extract(t2, &Kh, &Kl);

        if (sub(i, 5) < 0) {
            rc[i - 1] = round_fx(t2);
        }

        /* Stability check */
        if (sub(abs_s(Kh), 32750) > 0) {
            for (j = 0; j <= M_LPC; j++)
                A[j] = st->old_A[j];
            for (j = 0; j < 4; j++)
                rc[j] = 0;
            return 0;
        }

        /* Compute new LPC coeff: An[j] = A[j] + K*A[i-j] */
        for (j = 1; j < i; j++) {
            t0 = Mpy_32(Kh, Kl, Ah[i - j], Al[i - j]);
            t0 = L_add(t0, L_Comp(Ah[j], Al[j]));
            L_Extract(t0, &Anh[j], &Anl[j]);
        }
        t2 = L_shr(t2, 4);
        L_Extract(t2, &Anh[i], &Anl[i]);

        /* Alpha = Alpha * (1 - K^2) */
        t0 = Mpy_32(Kh, Kl, Kh, Kl);
        t0 = L_abs(t0);
        t0 = L_sub((Word32)0x7fffffffL, t0);
        L_Extract(t0, &hi, &lo);
        t0 = Mpy_32(alp_h, alp_l, hi, lo);

        /* Normalize Alpha */
        j = norm_l(t0);
        t0 = L_shl(t0, j);
        L_Extract(t0, &alp_h, &alp_l);
        alp_exp = add(alp_exp, j);

        /* Update: A = An */
        for (j = 1; j <= i; j++) {
            Ah[j] = Anh[j];
            Al[j] = Anl[j];
        }
    }

    A[0] = 4096;
    for (i = 1; i <= M_LPC; i++) {
        t0 = L_Comp(Ah[i], Al[i]);
        st->old_A[i] = A[i] = round_fx(L_shl(t0, 1));
    }

    return 0;
}
