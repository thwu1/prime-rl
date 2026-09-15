/*
 * Levinson-Durbin algorithm — double-precision fixed-point.
 *
 */

#ifndef LEVINSON_H
#define LEVINSON_H

#include "basicop.h"

#define M_LPC 10   /* LPC order */

typedef struct {
    Word16 old_A[M_LPC + 1];
} LevinsonState;

int  Levinson_init(LevinsonState **state);
int  Levinson_reset(LevinsonState *state);
void Levinson_exit(LevinsonState **state);

/*
 * Levinson-Durbin:
 *   Rh, Rl : autocorrelation in DPF format, size M_LPC+1
 *   A      : LP coefficients output, size M_LPC+1 (A[0]=4096)
 *   rc     : first 4 reflection coefficients
 * Returns 0 on success.
 */
int Levinson(LevinsonState *st,
             Word16 Rh[], Word16 Rl[],
             Word16 A[],  Word16 rc[]);

#endif /* LEVINSON_H */
