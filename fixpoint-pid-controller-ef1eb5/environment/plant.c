/*
 * Discrete second-order plant model implementation.
 *
 * The continuous system is:
 *   x1_dot = x2
 *   x2_dot = -omega_n^2 * x1 - 2*zeta*omega_n * x2 + omega_n^2 * u
 *   y      = x1
 *
 * Discretized using forward Euler with step Ts:
 *   x1[k+1] = x1[k] + Ts * x2[k]
 *   x2[k+1] = x2[k] + Ts * (-omega_n^2 * x1[k] - 2*zeta*omega_n*x2[k] + omega_n^2*u[k])
 *   y[k]    = x1[k]
 *
 */

#include "plant.h"

void plant_init(Plant *p, fix16_t omega_n, fix16_t zeta, fix16_t ts)
{
    p->x1 = 0;
    p->x2 = 0;

    /* omega_n^2 */
    fix16_t wn2 = fix16_smul(omega_n, omega_n);
    /* 2 * zeta * omega_n */
    fix16_t two_zeta_wn = fix16_smul(FIX16_FROM_INT(2),
                              fix16_smul(zeta, omega_n));

    /* Forward Euler state-space:
     * A = I + Ts * Ac, B = Ts * Bc
     * Ac = [[0, 1], [-wn2, -2*zeta*wn]]
     * Bc = [[0], [wn2]]
     */
    p->a11 = FIX16_ONE;                                     /* 1 + Ts*0 */
    p->a12 = ts;                                             /* 0 + Ts*1 = Ts */
    p->a21 = fix16_smul(ts, -wn2);                           /* 0 + Ts*(-wn2) */
    /* a22 = 1 + Ts*(-2*zeta*wn) = 1 - Ts*2*zeta*wn */
    p->a22 = fix16_ssub(FIX16_ONE, fix16_smul(ts, two_zeta_wn));
    p->b1  = 0;                                              /* Ts * 0 */
    p->b2  = fix16_smul(ts, wn2);                            /* Ts * wn2 */
}

fix16_t plant_step(Plant *p, fix16_t u)
{
    fix16_t y = p->x1;

    fix16_t x1_new = fix16_sadd(fix16_smul(p->a11, p->x1),
                     fix16_sadd(fix16_smul(p->a12, p->x2),
                                fix16_smul(p->b1, u)));

    fix16_t x2_new = fix16_sadd(fix16_smul(p->a21, p->x1),
                     fix16_sadd(fix16_smul(p->a22, p->x2),
                                fix16_smul(p->b2, u)));

    p->x1 = x1_new;
    p->x2 = x2_new;

    return y;
}
