/*
 * FIXED HLL approximate Riemann solver for the 1D shallow water equations.
 *
 */
#include "flux_kernels.h"
#include <math.h>

void hll_flux(double h_L, double h_R, double hu_L, double hu_R,
              double g, double *F_h, double *F_hu)
{
    double u_L = (h_L > 1e-10) ? hu_L / h_L : 0.0;
    double u_R = (h_R > 1e-10) ? hu_R / h_R : 0.0;
    double c_L = sqrt(g * fmax(h_L, 0.0));
    double c_R = sqrt(g * fmax(h_R, 0.0));

    double h_bar = 0.5 * (h_L + h_R);
    double denom_roe = sqrt(fmax(h_L, 0.0)) + sqrt(fmax(h_R, 0.0)) + 1e-30;
    double u_bar = (sqrt(fmax(h_L, 0.0)) * u_L + sqrt(fmax(h_R, 0.0)) * u_R)
                   / denom_roe;
    double c_bar = sqrt(g * fmax(h_bar, 0.0));

    /* FIX: s_R must use fmax, not fmin */
    double s_L = fmin(u_L - c_L, u_bar - c_bar);
    double s_R = fmax(u_R + c_R, u_bar + c_bar);

    double F_h_L  = hu_L;
    double F_h_R  = hu_R;
    double F_hu_L = hu_L * u_L + 0.5 * g * h_L * h_L;
    double F_hu_R = hu_R * u_R + 0.5 * g * h_R * h_R;

    if (s_L >= 0.0) {
        *F_h  = F_h_L;
        *F_hu = F_hu_L;
    } else if (s_R <= 0.0) {
        *F_h  = F_h_R;
        *F_hu = F_hu_R;
    } else {
        double inv_ds = 1.0 / (s_R - s_L + 1e-30);
        *F_h  = (s_R * F_h_L  - s_L * F_h_R
                 + s_L * s_R * (h_R - h_L)) * inv_ds;
        *F_hu = (s_R * F_hu_L - s_L * F_hu_R
                 + s_L * s_R * (hu_R - hu_L)) * inv_ds;
    }
}
