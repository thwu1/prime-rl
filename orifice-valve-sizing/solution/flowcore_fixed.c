/*
 * Flow measurement core computations — orifice plate metering.
 * FIXED version: corrects M2' denominator and expansibility exponent.
 *
 */

#include "flowcore.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

double orifice_C(double D, double Do, double rho, double mu, double m, int taps)
{
    double A_pipe = 0.25 * M_PI * D * D;
    double v = m / (A_pipe * rho);
    double Re_D = rho * v * D / mu;
    double Re_D_inv = 1.0 / Re_D;

    double beta = Do / D;
    double beta2 = beta * beta;
    double beta4 = beta2 * beta2;
    double beta8 = beta4 * beta4;

    double L1, L2_prime;
    switch (taps) {
        case TAP_CORNER:
            L1 = 0.0;
            L2_prime = 0.0;
            break;
        case TAP_FLANGE:
            L1 = 0.0254 / D;
            L2_prime = 0.0254 / D;
            break;
        case TAP_D:
            L1 = 1.0;
            L2_prime = 0.47;
            break;
        default:
            return -1.0;
    }

    double A = pow(19000.0 * beta * Re_D_inv, 0.8);
    /* FIX: denominator must be (1.0 - beta), not (1.0 + beta) */
    double M2_prime = 2.0 * L2_prime / (1.0 - beta);

    /* Upstream tap correction */
    double expnL1 = exp(-L1);
    double expnL2 = expnL1 * expnL1;
    double expnL3 = expnL1 * expnL2;

    double delta_C_upstream =
        (0.043 + expnL3 * expnL2 * expnL2 * (0.080 * expnL3 - 0.123))
        * (1.0 - 0.11 * A) * beta4 / (1.0 - beta4);

    /* Downstream tap correction */
    double t1 = log10(3700.0 * Re_D_inv);
    if (t1 < 0.0) t1 = 0.0;

    double delta_C_downstream =
        -0.031 * (M2_prime - 0.8 * pow(M2_prime, 1.1)) * pow(beta, 1.3)
        * (1.0 + 8.0 * t1);

    /* C_inf + slope term */
    double x1 = pow(1e6 * Re_D_inv, 0.3);
    double x2 = 22.7 - 0.0047 * Re_D;
    double t2 = x2 > x1 ? x2 : x1;

    double C_inf_C_s =
        0.5961
        + 0.0261 * beta2
        - 0.216 * beta8
        + 0.000521 * pow(1e6 * beta * Re_D_inv, 0.7)
        + (0.0188 + 0.0063 * A) * beta2 * beta * sqrt(beta) * t2;

    double C = C_inf_C_s + delta_C_upstream + delta_C_downstream;

    /* Small-diameter correction (D < 71.12 mm) */
    if (D < 0.07112) {
        double t3 = 2.8 - D / 0.0254;
        double delta_C_diameter = 0.011 * (0.75 - beta) * t3;
        C += delta_C_diameter;
    }

    return C;
}

double orifice_eps(double D, double Do, double P1, double P2, double k)
{
    double beta = Do / D;
    double beta2 = beta * beta;
    double beta4 = beta2 * beta2;
    /* FIX: exponent must be 1.0/k, not k */
    return 1.0 - (0.351 + beta4 * (0.93 * beta4 + 0.256))
               * (1.0 - pow(P2 / P1, 1.0 / k));
}

double orifice_flow(double D, double Do, double P1, double P2,
                    double rho, double mu, double k, int taps)
{
    double beta = Do / D;
    double beta2 = beta * beta;
    double beta4 = beta2 * beta2;
    double dP = P1 - P2;
    double eps = orifice_eps(D, Do, P1, P2, k);

    double D_beta = D * beta;
    double coeff = 0.25 * M_PI * D_beta * D_beta * eps
                   * sqrt(2.0 * rho * dP / (1.0 - beta4));

    double C = 0.6;
    int i;
    for (i = 0; i < 200; i++) {
        double m_val = coeff * C;
        double C_new = orifice_C(D, Do, rho, mu, m_val, taps);
        if (fabs(C_new - C) < 1e-12 * fabs(C_new)) {
            C = C_new;
            break;
        }
        C = C_new;
    }

    return coeff * C;
}
