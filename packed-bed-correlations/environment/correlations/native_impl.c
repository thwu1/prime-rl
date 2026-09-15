/*
 * Native implementations of packed-bed pressure drop correlations.
 * Compiled as a shared library for use via Python ctypes.
 */

#include <math.h>

/*
 * Idelchik (1989) packed-bed pressure drop correlation.
 */
double idelchik_dp(double dp, double voidage, double vs,
                   double rho, double mu, double L)
{
    double Re = rho * vs * dp / mu;
    Re = (0.45 / sqrt(voidage)) * Re;
    double right = 0.765 * pow(voidage, -4.2)
                   * (30.0 / Re + 3.0 * pow(Re, -0.7) + 0.3);
    double left = dp / (L * rho * vs * vs);
    return right / left;
}

/*
 * Harrison, Brunner & Hecker packed-bed pressure drop with wall correction.
 * has_dt: 0 = no tube diameter (use A=B=1), 1 = apply wall correction.
 */
double harrison_brunner_hecker_dp(double dp, double voidage, double vs,
                                  double rho, double mu, double L,
                                  double Dt, int has_dt)
{
    double Re = dp * rho * vs / mu;
    double h = 1.0 - voidage;
    double e3 = voidage * voidage * voidage;
    double A, B;

    if (!has_dt) {
        A = 1.0;
        B = 1.0;
    } else {
        A = 1.0 + M_PI * dp / (6.0 * Dt);
        A = A * A;
        B = 1.0 - M_PI * M_PI * dp / 24.0 / Dt * (1.0 - dp / (2.0 * Dt));
    }

    double fp = (119.8 * A + 4.63 * B * pow(Re / h, 5.0 / 6.0))
                * h * h / (e3 * Re);
    return fp * rho * vs * vs * L / dp;
}
