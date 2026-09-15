#ifndef PLANT_H
#define PLANT_H

/*
 * Discrete second-order plant model (provided, do not modify).
 *
 * Continuous transfer function:
 *   G(s) = omega_n^2 / (s^2 + 2*zeta*omega_n*s + omega_n^2)
 *
 * Discretized via zero-order hold (ZOH) with sampling period Ts.
 * State-space form: x[k+1] = A*x[k] + B*u[k], y[k] = C*x[k]
 *
 */

#include "fixpoint.h"

typedef struct {
    fix16_t x1;   /* state variable 1 */
    fix16_t x2;   /* state variable 2 */
    /* Precomputed discrete state-space matrices (ZOH) */
    fix16_t a11, a12, a21, a22;
    fix16_t b1, b2;
    /* c1=1, c2=0 (output = x1) */
} Plant;

/*
 * Initialize plant state-space matrices for given omega_n, zeta, Ts.
 * Uses Euler approximation of the ZOH discretization for the
 * second-order system.
 */
void plant_init(Plant *p, fix16_t omega_n, fix16_t zeta, fix16_t ts);

/*
 * Advance plant by one time step. Returns output y[k].
 */
fix16_t plant_step(Plant *p, fix16_t u);

#endif /* PLANT_H */
