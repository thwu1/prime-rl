#ifndef FLUX_KERNELS_H
#define FLUX_KERNELS_H

/*
 * HLL flux for the 1D shallow water equations.
 *
 * h_L, h_R   : water depth left/right of interface
 * hu_L, hu_R : discharge (h*u) left/right
 * g          : gravitational acceleration
 * F_h, F_hu  : output mass and momentum fluxes
 */
void hll_flux(double h_L, double h_R, double hu_L, double hu_R,
              double g, double *F_h, double *F_hu);

#endif /* FLUX_KERNELS_H */
