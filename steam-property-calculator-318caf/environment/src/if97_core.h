#ifndef IF97_CORE_H
#define IF97_CORE_H

/*
 * IAPWS-IF97 core computation library.
 * Provides Region 1 and Region 2 dimensionless Gibbs free energy
 * computations, saturation curve, and boundary equations.
 */

/* Region 1: dimensionless Gibbs free energy gamma and partial derivatives.
 * Caller supplies pi = P/16.53 and tau = 1386.0/T.
 * Results written through output pointers. */
void if97_gamma1(double pi, double tau,
                 double *g, double *gp, double *gpp,
                 double *gt, double *gtt, double *gpt);

/* Region 2 ideal part: gamma_0 and its derivatives.
 * Input: pi = P (MPa), tau = 540.0/T */
void if97_gamma2_ideal(double pi, double tau,
                       double *g0, double *g0p, double *g0pp,
                       double *g0t, double *g0tt);

/* Region 2 residual part: gamma_r and its derivatives.
 * Input: pi = P (MPa), tau = 540.0/T */
void if97_gamma2_res(double pi, double tau,
                     double *gr, double *grp, double *grpp,
                     double *grt, double *grtt, double *grpt);

/* Saturation pressure as function of temperature.
 * T in Kelvin, returns P in MPa. Valid 273.15-647.096 K. */
double if97_psat_t(double T);

/* Saturation temperature as function of pressure.
 * P in MPa, returns T in Kelvin. Valid 0.000611-22.064 MPa. */
double if97_tsat_p(double P);

/* Region 2-3 boundary pressure from temperature.
 * T in Kelvin, returns P in MPa. */
double if97_p23_t(double T);

#endif /* IF97_CORE_H */
