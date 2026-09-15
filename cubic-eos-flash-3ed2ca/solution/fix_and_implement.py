#!/usr/bin/env python3
"""
Fix defects in the PR EOS flash calculator and implement missing
phase stability analysis.

"""

import sys

# ── Fix 1: CMakeLists.txt filename typo ──
cmake = open("/app/CMakeLists.txt").read()
cmake = cmake.replace("flash_engne.cpp", "flash_engine.cpp")
with open("/app/CMakeLists.txt", "w") as f:
    f.write(cmake)
print("Fixed CMakeLists.txt typo")

# ── Fix 2: pr_eos.cpp — wrong co-volume constant (SRK → PR) ──
pr_eos = open("/app/src/pr_eos.cpp").read()
pr_eos = pr_eos.replace("0.08664035", "0.07779607")
with open("/app/src/pr_eos.cpp", "w") as f:
    f.write(pr_eos)
print("Fixed pr_bi constant (SRK Omega_b -> PR Omega_b)")

# ── Fix 3: pr_eos.cpp — missing kij in fugacity coefficient derivative ──
pr_eos = open("/app/src/pr_eos.cpp").read()
old_si = """        double Si = 0.0;
        for (int j = 0; j < nc; j++) {
            double aij = std::sqrt(ai[i] * ai[j]);
            Si += x[j] * aij;
        }"""

new_si = """        double Si = 0.0;
        for (int j = 0; j < nc; j++) {
            double kij_val = get_kij(comp_idx[i], comp_idx[j]);
            double aij = std::sqrt(ai[i] * ai[j]) * (1.0 - kij_val);
            Si += x[j] * aij;
        }"""

pr_eos = pr_eos.replace(old_si, new_si)
with open("/app/src/pr_eos.cpp", "w") as f:
    f.write(pr_eos)
print("Fixed missing kij in fugacity coefficient derivative")

# ── Fix 4: flash_engine.cpp — Rachford-Rice derivative bug ──
flash = open("/app/src/flash_engine.cpp").read()
flash = flash.replace(
    "dg -= z[i] * km1 / (d * d);",
    "dg -= z[i] * km1 * km1 / (d * d);"
)
with open("/app/src/flash_engine.cpp", "w") as f:
    f.write(flash)
print("Fixed Rachford-Rice derivative")

# ── Fix 5: Implement TPD phase stability analysis ──
flash = open("/app/src/flash_engine.cpp").read()

OLD_STABILITY = """// --- Phase stability via TPD ---
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
}"""

NEW_STABILITY = """// --- Phase stability via TPD (Michelsen 1982) ---
bool check_stability(
    const std::vector<double>& z,
    const std::vector<double>& ai,
    const std::vector<double>& bi,
    const std::vector<int>& comp_idx,
    double T, double P)
{
    int nc = (int)z.size();

    // Pure component: stable if above critical temperature
    if (nc == 1) {
        return T > COMP_DB[comp_idx[0]].Tc;
    }

    // Feed-phase fugacity coefficients (try both roots, pick lower Gibbs)
    double Z_liq, Z_vap;
    auto lnp_liq = ln_fugacity_coefficients(z, ai, bi, comp_idx, T, P, true, Z_liq);
    auto lnp_vap = ln_fugacity_coefficients(z, ai, bi, comp_idx, T, P, false, Z_vap);

    double g_liq = 0, g_vap = 0;
    for (int i = 0; i < nc; i++) {
        g_liq += z[i] * lnp_liq[i];
        g_vap += z[i] * lnp_vap[i];
    }
    // Add PV contribution for proper Gibbs comparison
    g_liq += Z_liq - 1.0 - std::log(Z_liq - z[0]); // simplified
    g_vap += Z_vap - 1.0 - std::log(Z_vap - z[0]); // simplified
    bool feed_liquid = (g_liq <= g_vap) && (Z_liq != Z_vap);
    auto& ln_phi_z = feed_liquid ? lnp_liq : lnp_vap;

    // d_i = ln(z_i) + ln(phi_z_i)
    std::vector<double> d(nc);
    for (int i = 0; i < nc; i++) {
        d[i] = std::log(std::max(z[i], 1e-30)) + ln_phi_z[i];
    }

    // Try vapor-like and liquid-like trial phases
    for (int trial = 0; trial < 2; trial++) {
        bool trial_liq = (trial == 1);

        // Wilson K-factor initialization
        std::vector<double> W(nc);
        for (int i = 0; i < nc; i++) {
            const auto& c = COMP_DB[comp_idx[i]];
            double Ki = (c.Pc / P) * std::exp(5.373 * (1.0 + c.omega) * (1.0 - c.Tc / T));
            if (trial_liq) Ki = 1.0 / Ki;
            W[i] = z[i] * Ki;
        }

        // Successive substitution on modified tangent plane
        for (int iter = 0; iter < 500; iter++) {
            double sW = 0;
            for (int i = 0; i < nc; i++) sW += W[i];
            if (sW < 1e-30) break;

            std::vector<double> w(nc);
            for (int i = 0; i < nc; i++) w[i] = W[i] / sW;

            double Zt;
            auto lnpw = ln_fugacity_coefficients(w, ai, bi, comp_idx, T, P, trial_liq, Zt);

            double mc = 0;
            for (int i = 0; i < nc; i++) {
                double Wn = std::exp(d[i] - lnpw[i]);
                if (W[i] > 1e-30) {
                    mc = std::max(mc, std::abs(std::log(std::max(Wn, 1e-30) / W[i])));
                }
                W[i] = Wn;
            }
            if (mc < 1e-10) break;
        }

        // Evaluate modified TPD: tm = 1 - sum(W)
        double sW = 0;
        for (int i = 0; i < nc; i++) sW += W[i];

        if (sW > 1.0 + 1e-8) {
            return false;  // Unstable — at least one trial found negative TPD
        }
    }

    return true;  // Stable — no trial phase found instability
}"""

flash = flash.replace(OLD_STABILITY, NEW_STABILITY)
with open("/app/src/flash_engine.cpp", "w") as f:
    f.write(flash)
print("Implemented TPD phase stability analysis")

print("All fixes applied successfully.")
