/* Cubic equation solver for PR EOS compressibility factor.
 *
 * Solves Z^3 + c2*Z^2 + c1*Z + c0 = 0 where coefficients are derived
 * from dimensionless PR EOS parameters A and B.
 *
 */

#include <math.h>

static double cube_root(double x) {
    if (x >= 0.0) return pow(x, 1.0 / 3.0);
    return -pow(-x, 1.0 / 3.0);
}

int solve_cubic_eos(double A, double B, double roots[3]) {
    /* PR EOS cubic coefficients in Z */
    double c2 = -(1.0 - B);
    double c1 = A - 3.0 * B * B - 2.0 * B;
    double c0 = -(A * B - B * B - B * B * B);

    /* Depressed cubic: t^3 + pt + q = 0, with Z = t - c2/3 */
    double c2_sq = c2 * c2;
    double p = c1 - c2_sq / 3.0;
    double q = 2.0 * c2 * c2_sq / 27.0 + c2 * c1 / 3.0 + c0;

    double disc = q * q / 4.0 + p * p * p / 27.0;

    double Zs[3];
    int nroots;

    if (disc > 1e-14) {
        /* One real root (Cardano) */
        double sqrt_disc = sqrt(disc);
        double u = cube_root(-q / 2.0 + sqrt_disc);
        double v = cube_root(-q / 2.0 - sqrt_disc);
        Zs[0] = u + v - c2 / 3.0;
        nroots = 1;
    } else {
        if (fabs(p) < 1e-30) {
            Zs[0] = -c2 / 3.0;
            nroots = 1;
        } else {
            /* Three real roots (trigonometric method) */
            double m = 2.0 * sqrt(-p / 3.0);
            double cos_arg = 3.0 * q / (p * m);
            if (cos_arg < -1.0) cos_arg = -1.0;
            if (cos_arg > 1.0) cos_arg = 1.0;
            double theta = acos(cos_arg) / 3.0;
            int k;
            for (k = 0; k < 3; k++) {
                Zs[k] = m * cos(theta - 2.0 * M_PI * k / 3.0) - c2 / 3.0;
            }
            nroots = 3;
        }
    }

    /* Sort ascending via bubble sort */
    {
        int i, j;
        for (i = 0; i < nroots - 1; i++) {
            for (j = 0; j < nroots - i - 1; j++) {
                if (Zs[j] > Zs[j + 1]) {
                    double tmp = Zs[j];
                    Zs[j] = Zs[j + 1];
                    Zs[j + 1] = tmp;
                }
            }
        }
    }

    /* Copy to output array */
    {
        int i;
        for (i = 0; i < nroots; i++) {
            roots[i] = Zs[i];
        }
    }

    return nroots;
}
