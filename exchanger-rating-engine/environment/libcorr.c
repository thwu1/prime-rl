/* Bell-Delaware correlations — C implementation for performance-critical paths.
 *
 * Provides crossflow area computation and bypass correction factor.
 * Compiled as a shared library loaded by bell_delaware.py via ctypes.
 *
 */

#include <math.h>

/*
 * Compute crossflow area at bundle centerline S_m [m^2].
 *
 * Taborek (1983) Eq. 3.3.8-1:
 *   S_m = B * (D_s - D_otl + D_otl * (P_t - d_o) / P_t)
 *
 * Parameters:
 *   B     - central baffle spacing [m]
 *   D_s   - shell inside diameter [m]
 *   D_otl - outer tube limit diameter [m]
 *   P_t   - tube pitch [m]
 *   d_o   - tube outside diameter [m]
 */
double compute_Sm(double B, double D_s, double D_otl, double P_t, double d_o) {
    return B * (D_s - D_otl + (P_t - d_o) / P_t);
}

/*
 * Compute bypass correction factor J_b.
 *
 * Taborek (1983) Eq. 3.3.10-3:
 *   C_bh = 1.25 (Re >= 100), 1.35 (Re < 100)
 *   r_ss = N_ss / N_c
 *   If r_ss >= 0.5: J_b = 1.0
 *   Else: J_b = exp(-C_bh * F_bp * [1 - (2*r_ss)^(1/3)])
 *
 * Parameters:
 *   F_bp - bypass fraction (S_b / S_m)
 *   N_ss - number of sealing strip pairs
 *   N_c  - number of crossflow tube rows
 *   Re   - shell-side Reynolds number
 */
double compute_Jb(double F_bp, int N_ss, double N_c, double Re) {
    double C_bh = (Re >= 100.0) ? 1.25 : 1.35;
    double r_ss = (N_c > 0.0) ? (double)N_ss / N_c : 0.0;
    if (r_ss >= 0.5) return 1.0;
    return exp(-C_bh * F_bp * (1.0 - 2.0 * r_ss));
}
