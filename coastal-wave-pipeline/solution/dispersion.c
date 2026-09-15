/* Dispersion relation solver for linear wave theory.
 * Solves omega^2 = g * k * tanh(k * d) via Newton-Raphson.
 *
 */

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const double G = 9.81;

/*
 * solve_dispersion: solve the linear wave dispersion relation.
 *   T   - wave period (s)
 *   d   - water depth (m)
 *   out - 5-element output array: [L, C, Cg, k, n]
 * Returns 0 on success.
 */
int solve_dispersion(double T, double d, double *out) {
    double omega = 2.0 * M_PI / T;
    double Lo = G * T * T / (2.0 * M_PI);
    double L;

    if (d / Lo > 0.5) {
        /* Deep water */
        L = Lo;
    } else {
        /* Eckart approximation as initial guess */
        L = Lo * sqrt(tanh(2.0 * M_PI * d / Lo));
        if (L < 1e-6) L = Lo * 0.1;

        /* Newton-Raphson on f(L) = L - Lo * tanh(2*pi*d/L) */
        for (int i = 0; i < 200; i++) {
            double kd = 2.0 * M_PI * d / L;
            double tanh_kd = tanh(kd);
            double f_val = L - Lo * tanh_kd;
            double cosh_kd = cosh(kd);
            double fp = 1.0 + Lo * (2.0 * M_PI * d / (L * L)) / (cosh_kd * cosh_kd);
            double L_new = L - f_val / fp;
            if (L_new < 1e-10) L_new = L * 0.5;
            if (fabs(L_new - L) < 1e-10) {
                L = L_new;
                break;
            }
            L = L_new;
        }
    }

    double k = 2.0 * M_PI / L;
    double C = L / T;
    double kd = k * d;
    double n;

    if (kd > 50.0) {
        n = 0.5;
    } else {
        double sinh_2kd = sinh(2.0 * kd);
        if (fabs(sinh_2kd) < 1e-30) {
            n = 1.0;  /* shallow water limit */
        } else {
            n = 0.5 * (1.0 + 2.0 * kd / sinh_2kd);
        }
    }

    double Cg = n * C;

    out[0] = L;
    out[1] = C;
    out[2] = Cg;
    out[3] = k;
    out[4] = n;

    return 0;
}
