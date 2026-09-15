#include "pr_eos.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>


double pr_m(double omega) {
    if (omega <= 0.491) {
        return 0.37464 + 1.54226 * omega - 0.26992 * omega * omega;
    }
    return 0.379642 + 1.48503 * omega
         - 0.164423 * omega * omega
         + 0.016666 * omega * omega * omega;
}

double pr_alpha(double T, double Tc, double omega) {
    double m = pr_m(omega);
    double sq = 1.0 + m * (1.0 - std::sqrt(T / Tc));
    return sq * sq;
}

double pr_ai(const Component& c, double T) {
    return 0.45723553 * R_GAS * R_GAS * c.Tc * c.Tc / c.Pc
           * pr_alpha(T, c.Tc, c.omega);
}

double pr_bi(const Component& c) {
    return 0.08664035 * R_GAS * c.Tc / c.Pc;
}

// Solve PR cubic: Z^3 - (1-B)Z^2 + (A-2B-3B^2)Z - (AB-B^2-B^3) = 0
std::vector<double> solve_cubic(double A, double B) {
    double c2 = -(1.0 - B);
    double c1 = A - 3.0 * B * B - 2.0 * B;
    double c0 = -(A * B - B * B - B * B * B);

    // Depressed cubic t^3 + pt + q = 0 via Z = t - c2/3
    double p = c1 - c2 * c2 / 3.0;
    double q = c0 - c1 * c2 / 3.0 + 2.0 * c2 * c2 * c2 / 27.0;

    double D = q * q / 4.0 + p * p * p / 27.0;
    double shift = -c2 / 3.0;

    std::vector<double> roots;

    if (D > 1e-12) {
        double sd = std::sqrt(D);
        double u = std::cbrt(-q / 2.0 + sd);
        double v = std::cbrt(-q / 2.0 - sd);
        roots.push_back(u + v + shift);
    } else if (D < -1e-12) {
        double r = std::sqrt(-p * p * p / 27.0);
        double theta = std::acos(std::clamp(-q / (2.0 * r), -1.0, 1.0));
        double m = 2.0 * std::cbrt(r);
        for (int k = 0; k < 3; k++) {
            roots.push_back(m * std::cos((theta + 2.0 * M_PI * k) / 3.0) + shift);
        }
    } else {
        double u = std::cbrt(-q / 2.0);
        roots.push_back(2.0 * u + shift);
        roots.push_back(-u + shift);
    }

    // Keep physically valid roots (Z > B)
    std::vector<double> valid;
    for (double z : roots) {
        if (z > B + 1e-12) valid.push_back(z);
    }
    if (valid.empty()) {
        for (double z : roots) {
            if (z > 0) valid.push_back(z);
        }
    }
    if (valid.empty()) {
        valid.push_back(roots.back());
    }

    std::sort(valid.begin(), valid.end());
    return valid;
}

std::vector<double> ln_fugacity_coefficients(
    const std::vector<double>& x,
    const std::vector<double>& ai,
    const std::vector<double>& bi,
    const std::vector<int>& comp_idx,
    double T, double P,
    bool want_liquid,
    double& Z_out)
{
    int nc = (int)x.size();

    // Classical mixing rules: a_mix = sum_i sum_j x_i x_j a_ij
    double a_mix = 0.0, b_mix = 0.0;
    for (int i = 0; i < nc; i++) {
        b_mix += x[i] * bi[i];
        for (int j = 0; j < nc; j++) {
            double kij = get_kij(comp_idx[i], comp_idx[j]);
            double aij = std::sqrt(ai[i] * ai[j]) * (1.0 - kij);
            a_mix += x[i] * x[j] * aij;
        }
    }

    double A = a_mix * P / (R_GAS * R_GAS * T * T);
    double B = b_mix * P / (R_GAS * T);

    auto roots = solve_cubic(A, B);
    Z_out = want_liquid ? roots.front() : roots.back();

    // ln(phi_i) = bi/bm*(Z-1) - ln(Z-B)
    //   - A/(2*sqrt(2)*B) * [2*S_i/a_mix - bi/bm] * ln[(Z+(1+sqrt2)*B)/(Z+(1-sqrt2)*B)]
    // where S_i = sum_j x_j * a_ij
    std::vector<double> lnphi(nc);
    for (int i = 0; i < nc; i++) {
        double Si = 0.0;
        for (int j = 0; j < nc; j++) {
            double aij = std::sqrt(ai[i] * ai[j]);
            Si += x[j] * aij;
        }

        double bi_bm = bi[i] / b_mix;
        double logterm = std::log(
            (Z_out + (1.0 + SQRT2) * B) /
            (Z_out + (1.0 - SQRT2) * B));

        lnphi[i] = bi_bm * (Z_out - 1.0)
                  - std::log(Z_out - B)
                  - A / (2.0 * SQRT2 * B) * (2.0 * Si / a_mix - bi_bm) * logterm;
    }
    return lnphi;
}
