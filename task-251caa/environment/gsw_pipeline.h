#ifndef GSW_PIPELINE_H
#define GSW_PIPELINE_H

/* TEOS-10 NaN sentinel value */
#define GSW_INVALID_VALUE 9e90
#define GSW_ERROR_LIMIT 1e10

/* Check if a value is valid (not a TEOS-10 NaN sentinel) */
int is_valid_value(double val);

/*
 * Specific volume of seawater from the 75-term polynomial.
 * SA: Absolute Salinity (g/kg)
 * CT: Conservative Temperature (deg C)
 * p:  Sea pressure (dbar) = absolute pressure - 10.1325 dbar
 * Returns: specific volume (m^3/kg)
 */
double gsw_specvol(double sa, double ct, double p);

/*
 * Specific volume plus thermal expansion and haline contraction coefficients.
 * alpha = -(1/v) * dv/dCT  (thermal expansion, 1/K)
 * beta  =  (1/v) * dv/dSA  (haline contraction, kg/g)
 */
void gsw_specvol_alpha_beta(double sa, double ct, double p,
                            double *specvol, double *alpha, double *beta);

/*
 * In-situ density of seawater (kg/m^3).
 */
double gsw_rho(double sa, double ct, double p);

/*
 * Potential density anomaly: rho(SA, CT, p=0) - 1000 (kg/m^3).
 */
double gsw_sigma0(double sa, double ct);

/*
 * Buoyancy frequency squared (N^2) for a vertical profile.
 * sa, ct, p: arrays of length n (one cast)
 * grav: pre-computed gravity at each level (m/s^2), array of length n
 * n: number of levels in the cast
 * n2: output array of length n-1 (N^2 at mid-levels)
 * p_mid: output array of length n-1 (pressure at mid-levels)
 */
void gsw_nsquared(const double *sa, const double *ct, const double *p,
                  const double *grav, int n, double *n2, double *p_mid);

#endif /* GSW_PIPELINE_H */
