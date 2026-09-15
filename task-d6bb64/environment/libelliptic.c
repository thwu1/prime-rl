
/*
 * Native C implementation of core elliptic function routines for the
 * elliptic filter design pipeline. Provides Landen sequence computation,
 * the complete elliptic integral K(k), and the Jacobian elliptic
 * function cd(u, k) with full complex argument support.
 *
 * These routines are loaded by the Python layer via ctypes for
 * performance-critical numerical evaluation.
 */

#include <math.h>
#include <string.h>
#include "libelliptic.h"

/*
 * Compute the descending Landen sequence starting from modulus k.
 * The descending Landen transformation is:
 *   k_{n+1} = (k_n / (1 + k_n'))^2  where k_n' = sqrt(1 - k_n^2)
 * This reduces k toward 0, where elliptic functions become trigonometric.
 */
LandenResult landen_sequence_c(double k, int n) {
    LandenResult result;
    memset(&result, 0, sizeof(result));
    if (n > MAX_LANDEN) n = MAX_LANDEN;

    result.values[0] = k;
    result.length = 1;
    double ki = k;

    for (int i = 1; i < n; i++) {
        double kp = sqrt(1.0 - ki * ki);
        double ratio = ki / (1.0 + kp);
        ki = ratio * ratio;
        result.values[i] = ki;
        result.length = i + 1;
        if (ki < 1e-18) break;
    }
    return result;
}

/*
 * Complete elliptic integral of the first kind K(k) via Landen
 * product formula:
 *   K(k) = (pi/2) * prod_{i=1}^{M} (1 + k_{-i})
 * where k_{-i} are the descending Landen sequence elements.
 */
double complete_elliptic_K_c(double k) {
    if (k < 1e-15) return M_PI / 2.0;
    if (k > 1.0 - 1e-15) return 1e15;

    LandenResult seq = landen_sequence_c(k, 30);
    double K = M_PI / 2.0;

    for (int i = 0; i < seq.length; i++) {
        K *= (1.0 + seq.values[i]);
    }
    return K;
}

/*
 * Jacobian elliptic function cd(u, k) = cn(u,k)/dn(u,k) for complex
 * argument u, computed via ascending Landen recursion.
 *
 * At the bottom of the Landen sequence (k ~ 0), cd ~ cos.
 * The ascending recursion reconstructs cd at the original modulus:
 *   w_{n+1} = (1 + k_n) * w_n / (1 + k_n * w_n^2)
 *
 * For complex w, the squaring w*w and division are done in full
 * complex arithmetic.
 */
CmplxResult elliptic_cd_c(double u_re, double u_im, double k) {
    CmplxResult result;

    if (k < 1e-15) {
        /* cd(u, 0) = cos(u) for complex u:
         * cos(a + bi) = cos(a)*cosh(b) - i*sin(a)*sinh(b) */
        result.real = cos(u_re) * cosh(u_im);
        result.imag = -sin(u_re) * sinh(u_im);
        return result;
    }

    LandenResult seq = landen_sequence_c(k, 30);
    double K = complete_elliptic_K_c(k);

    /* Normalized argument: x = u / K(k) */
    double x_re = u_re / K;
    double x_im = u_im / K;

    /* Initial value: w = cos(pi * x / 2) for complex x */
    double arg_re = M_PI * x_re / 2.0;
    double arg_im = M_PI * x_im / 2.0;
    double w_re = cos(arg_re) * cosh(arg_im);
    double w_im = -sin(arg_re) * sinh(arg_im);

    /* Ascending Landen recursion:
     * w_{n+1} = (1 + k_n) * w_n / (1 + k_n * w_n^2)
     * where k_n = seq[i+1] (the lower/source modulus) */
    for (int i = seq.length - 2; i >= 0; i--) {
        double ki = seq.values[i + 1];

        /* Denominator: 1 + ki * w * w
         * For complex w: w*w = (re^2 - im^2, 2*re*im) */
        double denom_re = 1.0 + ki * w_re;
        double denom_im = ki * w_im;

        /* Numerator: (1 + ki) * w */
        double num_re = (1.0 + ki) * w_re;
        double num_im = (1.0 + ki) * w_im;

        /* Complex division: (a+bi)/(c+di) = ((ac+bd) + (bc-ad)i) / (c^2+d^2) */
        double denom_mag2 = denom_re * denom_re + denom_im * denom_im;
        w_re = (num_re * denom_re + num_im * denom_im) / denom_mag2;
        w_im = (num_im * denom_re - num_re * denom_im) / denom_mag2;
    }

    result.real = w_re;
    result.imag = w_im;
    return result;
}
