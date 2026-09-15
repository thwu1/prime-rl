/*
 * Levinson-Durbin algorithm — STUB implementation.
 * TODO: implement the double-precision fixed-point Levinson-Durbin algorithm.
 *
 */

#include <stdlib.h>
#include <stdio.h>
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
    int i;
    (void)st; (void)Rh; (void)Rl;

    /* STUB: returns flat spectrum (no prediction) */
    A[0] = 4096;
    for (i = 1; i <= M_LPC; i++)
        A[i] = 0;
    for (i = 0; i < 4; i++)
        rc[i] = 0;
    return 0;
}
