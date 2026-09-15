/* Inverse standard normal CDF using Acklam's rational approximation.
   Reference: Peter Acklam, "An algorithm for computing the inverse
   normal cumulative distribution function" (2010). */

#include <math.h>
#include "qrng.h"

static const double A[] = {
    -3.969683028665376e+01, 2.209460984245205e+02,
    -2.759285104469687e+02, 1.383577518672690e+02,
    -3.066479806614716e+01, 2.506628277459239e+00
};

static const double B[] = {
    -5.447609879822406e+01, 1.615858368580409e+02,
    -1.556989798598866e+02, 6.680131188771972e+01,
    -1.328068155288572e+01
};

static const double C[] = {
    -7.784894002430293e-03, -3.223964580411365e-01,
    -2.400758277161838e+00, -2.549732539343734e+00,
     4.374664141464968e+00,  2.938163982698783e+00
};

static const double D[] = {
    7.784695709041462e-03, 3.224671290700398e-01,
    2.445134137142996e+00, 3.754408661907416e+00
};

#define P_LOW  0.02425
#define P_HIGH (1.0 - P_LOW)

double norm_inv(double u) {
    double q, r, x;

    if (u < P_LOW) {
        /* Lower tail region */
        q = sqrt(-log(u));
        x = (((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) /
            ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0);
    } else if (u <= P_HIGH) {
        /* Central region */
        q = u - 0.5;
        r = q * q;
        x = (((((A[0]*r + A[1])*r + A[2])*r + A[3])*r + A[4])*r + A[5]) * q /
            (((((B[0]*r + B[1])*r + B[2])*r + B[3])*r + B[4])*r + 1.0);
    } else {
        /* Upper tail region */
        q = sqrt(-log(1.0 - u));
        x = -(((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) /
             ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0);
    }

    return x;
}
