/*
 * Atmospheric and clear-sky radiation calculations.
 * Implements selected ASCE-EWRI 2005 functions for use via Python ctypes.
 *
 */

#include <math.h>
#include "atmos.h"

double air_pressure(double elev, int mode) {
    double base = (293.0 - 0.0065 * elev) / 293.0;
    if (mode == 0) {
        /* ASCE-EWRI (2005) Eq. 3 */
        return 101.3 * pow(base, 5.26);
    } else {
        /* RefET full barometric exponent */
        return 101.3 * pow(base, 9.8 / (0.0065 * 286.9));
    }
}

double precipitable_water(double pair, double ea) {
    return pair * 0.14 * ea + 2.1;
}

double sin_beta_24_daily(double lat, double doy) {
    double doy_frac = doy * 2.0 * M_PI / 365.0;
    return sin(0.85 + 0.3 * lat * sin(doy_frac - 1.39) - 0.42 * lat * lat);
}

double sin_beta_hourly(double lat, double delta, double omega) {
    return sin(lat) * sin(delta) + cos(lat) * cos(delta) * cos(omega);
}

double rso_clearsky(double ra, double pair, double ea,
                    double sin_beta, double min_sin_beta) {
    double w = precipitable_water(pair, ea);
    double sb = sin_beta;
    if (sb < min_sin_beta) sb = min_sin_beta;

    double kb = 0.98 * exp((-0.00146 * pair) / sb
                           - 0.075 * pow(w / sb, 0.4));
    double kd = fmin(-0.36 * kb + 0.35, 0.82 * kb + 0.18);
    return (kb + kd) * ra;
}
