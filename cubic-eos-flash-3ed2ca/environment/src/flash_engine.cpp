#include "flash_engine.h"
#include "pr_eos.h"
#include <cmath>
#include <algorithm>
#include <iostream>


// --- Wilson K-factor initialization ---
static std::vector<double> wilson_K(const std::vector<int>& idx, double T, double P) {
    int nc = (int)idx.size();
    std::vector<double> K(nc);
    for (int i = 0; i < nc; i++) {
        const auto& c = COMP_DB[idx[i]];
        K[i] = (c.Pc / P) * std::exp(5.373 * (1.0 + c.omega) * (1.0 - c.Tc / T));
    }
    return K;
}

// --- Rachford-Rice objective function ---
static double rr_g(const std::vector<double>& z, const std::vector<double>& K, double V) {
    double g = 0.0;
    for (size_t i = 0; i < z.size(); i++) {
        double km1 = K[i] - 1.0;
        g += z[i] * km1 / (1.0 + V * km1);
    }
    return g;
}

// --- Solve Rachford-Rice for vapor fraction V via Newton + bisection ---
static double solve_RR(const std::vector<double>& z, const std::vector<double>& K) {
    int nc = (int)z.size();

    // Whitson-Michelsen bounds
    double Vmin = 0.0, Vmax = 1.0;
    for (int i = 0; i < nc; i++) {
        double km1 = K[i] - 1.0;
        if (std::abs(km1) < 1e-15) continue;
        double vb = 1.0 / (1.0 - K[i]);
        if (K[i] > 1.0) {
            Vmax = std::min(Vmax, vb);
        } else {
            Vmin = std::max(Vmin, vb);
        }
    }
    Vmin += 1e-10;
    Vmax -= 1e-10;
    if (Vmin >= Vmax) { Vmin = 1e-8; Vmax = 1.0 - 1e-8; }

    double V = 0.5 * (Vmin + Vmax);
    for (int it = 0; it < 200; it++) {
        double g = rr_g(z, K, V);
        if (std::abs(g) < 1e-14) break;

        double dg = 0.0;
        for (int i = 0; i < nc; i++) {
            double km1 = K[i] - 1.0;
            double d = 1.0 + V * km1;
            dg -= z[i] * km1 / (d * d);
        }

        if (std::abs(dg) < 1e-30) break;
        double Vn = V - g / dg;
        if (Vn <= Vmin || Vn >= Vmax) {
            if (g > 0) Vmin = V; else Vmax = V;
            V = 0.5 * (Vmin + Vmax);
        } else {
            V = Vn;
        }
    }
    return V;
}

// --- Phase stability via TPD ---
bool check_stability(
    const std::vector<double>& z,
    const std::vector<double>& ai,
    const std::vector<double>& bi,
    const std::vector<int>& comp_idx,
    double T, double P)
{
    // Tangent-plane distance (TPD) analysis
    // Returns true if feed is STABLE (single-phase)
    // TODO: implement proper TPD minimization with multiple trial phases
    return false;  // Always reports unstable
}

// --- Main flash driver ---
FlashResult run_flash(
    const std::string& name,
    const std::vector<int>& comp_idx,
    const std::vector<double>& z,
    double T, double P)
{
    int nc = (int)z.size();
    FlashResult res;
    res.problem_name = name;
    res.converged = false;
    res.two_phase = false;
    res.V = -1;
    res.Z_L = res.Z_V = 0;
    res.x.assign(nc, 0);
    res.y.assign(nc, 0);
    res.ln_phi_L.assign(nc, 0);
    res.ln_phi_V.assign(nc, 0);

    // Compute pure-component PR parameters at this T
    std::vector<double> a_i(nc), b_i(nc);
    for (int i = 0; i < nc; i++) {
        a_i[i] = pr_ai(COMP_DB[comp_idx[i]], T);
        b_i[i] = pr_bi(COMP_DB[comp_idx[i]]);
    }

    // Phase stability test
    if (check_stability(z, a_i, b_i, comp_idx, T, P)) {
        // Single-phase — report feed properties
        res.converged = true;
        res.two_phase = false;
        res.x = z;
        res.y = z;
        double Z_feed;
        // Use vapor root for feed (supercritical single-phase)
        res.ln_phi_L = ln_fugacity_coefficients(z, a_i, b_i, comp_idx, T, P, false, Z_feed);
        res.Z_L = Z_feed;
        res.Z_V = Z_feed;
        res.ln_phi_V = res.ln_phi_L;
        return res;
    }

    // --- Two-phase: successive substitution flash ---
    auto K = wilson_K(comp_idx, T, P);

    std::vector<double> x(nc), y(nc);

    for (int outer = 0; outer < 800; outer++) {
        double V = solve_RR(z, K);
        V = std::clamp(V, 1e-12, 1.0 - 1e-12);

        // Phase compositions from K-factors
        double sx = 0, sy = 0;
        for (int i = 0; i < nc; i++) {
            x[i] = z[i] / (1.0 + V * (K[i] - 1.0));
            y[i] = K[i] * x[i];
            sx += x[i]; sy += y[i];
        }
        for (int i = 0; i < nc; i++) { x[i] /= sx; y[i] /= sy; }

        double ZL, ZV;
        auto lnpL = ln_fugacity_coefficients(x, a_i, b_i, comp_idx, T, P, true,  ZL);
        auto lnpV = ln_fugacity_coefficients(y, a_i, b_i, comp_idx, T, P, false, ZV);

        // Update K-factors from fugacity ratio
        double maxchg = 0;
        for (int i = 0; i < nc; i++) {
            double lnK_new = lnpL[i] - lnpV[i];
            double Knew = std::exp(lnK_new);
            if (K[i] > 1e-30) {
                maxchg = std::max(maxchg, std::abs(std::log(Knew / K[i])));
            }
            K[i] = Knew;
        }

        if (maxchg < 1e-10) {
            // Recompute final compositions with converged K
            V = solve_RR(z, K);
            V = std::clamp(V, 1e-12, 1.0 - 1e-12);
            sx = sy = 0;
            for (int i = 0; i < nc; i++) {
                x[i] = z[i] / (1.0 + V * (K[i] - 1.0));
                y[i] = K[i] * x[i];
                sx += x[i]; sy += y[i];
            }
            for (int i = 0; i < nc; i++) { x[i] /= sx; y[i] /= sy; }

            lnpL = ln_fugacity_coefficients(x, a_i, b_i, comp_idx, T, P, true,  ZL);
            lnpV = ln_fugacity_coefficients(y, a_i, b_i, comp_idx, T, P, false, ZV);

            res.converged = true;
            res.two_phase = true;
            res.V = V;
            res.x = x; res.y = y;
            res.ln_phi_L = lnpL; res.ln_phi_V = lnpV;
            res.Z_L = ZL; res.Z_V = ZV;
            return res;
        }
    }

    // Did not converge
    res.converged = false;
    res.two_phase = true;
    return res;
}
