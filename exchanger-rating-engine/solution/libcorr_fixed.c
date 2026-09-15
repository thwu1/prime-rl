/* Bell-Delaware correlations — C implementation (FIXED).
 *
 */

#include <math.h>

/* Compute crossflow area at bundle centerline S_m [m^2]. */
double compute_Sm(double B, double D_s, double D_otl, double P_t, double d_o) {
    /* FIX: D_otl multiplier restored on tube-pitch clearance term */
    return B * (D_s - D_otl + D_otl * (P_t - d_o) / P_t);
}

/* Compute bypass correction factor J_b. */
double compute_Jb(double F_bp, int N_ss, double N_c, double Re) {
    double C_bh = (Re >= 100.0) ? 1.25 : 1.35;
    double r_ss = (N_c > 0.0) ? (double)N_ss / N_c : 0.0;
    if (r_ss >= 0.5) return 1.0;
    /* FIX: cube root exponent restored on (2*r_ss) term */
    return exp(-C_bh * F_bp * (1.0 - pow(2.0 * r_ss, 1.0 / 3.0)));
}
