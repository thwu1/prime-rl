
#ifndef VORTEX_H
#define VORTEX_H

/*
 * Biot-Savart velocity primitives for vortex filaments.
 * All functions compute induced velocity per unit circulation
 * (the 1/(4*pi) factor is NOT included).
 *
 * P, A, B, Q, d are pointers to 3-element double arrays.
 * vel is a pointer to a 3-element output array.
 */

/* Induced velocity at P from a finite vortex segment A -> B. */
void biot_savart_finite(const double *P, const double *A, const double *B,
                        double *vel);

/* Induced velocity at P from a semi-infinite vortex starting at Q,
   extending to infinity in direction d (unit vector). */
void biot_savart_semi_inf(const double *P, const double *Q, const double *d,
                          double *vel);

/* Horseshoe vortex: bound segment A->B plus two semi-infinite trailing
   legs aligned with the freestream direction d_inf. */
void horseshoe_velocity(const double *P, const double *A, const double *B,
                        const double *d_inf, double *vel);

#endif
