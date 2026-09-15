#ifndef ATMOS_H
#define ATMOS_H

/*
 * Atmospheric and clear-sky radiation calculations.
 * Functions are called from Python via ctypes.
 *
 */

/* Air pressure [kPa] from elevation [m].
   mode: 0 = ASCE (Eq. 3), 1 = RefET (full barometric) */
double air_pressure(double elev, int mode);

/* Precipitable water [mm] (Eq. D.3) */
double precipitable_water(double pair, double ea);

/* Sin of mean daily sun angle (Eq. D.5) */
double sin_beta_24_daily(double lat, double doy);

/* Sin of instantaneous sun angle (Eq. D.6) */
double sin_beta_hourly(double lat, double delta, double omega);

/* Full clear-sky solar radiation [MJ m-2] (Appendix D)
   ra:           extraterrestrial radiation
   pair:         air pressure [kPa]
   ea:           actual vapor pressure [kPa]
   sin_beta:     sun angle sine (from sin_beta_24_daily or sin_beta_hourly)
   min_sin_beta: lower clamp (0.1 for daily, 0.01 for hourly) */
double rso_clearsky(double ra, double pair, double ea,
                    double sin_beta, double min_sin_beta);

#endif /* ATMOS_H */
