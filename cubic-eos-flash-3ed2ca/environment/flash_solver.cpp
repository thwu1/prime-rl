// flash_solver.cpp
// Multi-component Peng-Robinson isothermal VLE flash calculator
// Computes vapor-liquid equilibrium for hydrocarbon/gas mixtures
// using successive substitution with Wilson K-value initialization.
//

#include <cmath>
#include <vector>
#include <string>
#include <algorithm>
#include <numeric>
#include <cfloat>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static const double R_GAS = 8.314472;  // Universal gas constant [J/(mol·K)]
static const double SQRT2 = 1.4142135623730951;

// ---------- Component database ----------

struct Component {
    const char* name;
    double Tc;     // Critical temperature [K]
    double Pc;     // Critical pressure [Pa]
    double omega;  // Acentric factor [-]
};

static const Component COMP_DB[] = {
    {"Methane",   190.564,  4599200.0,  0.01142},
    {"Ethane",    305.322,  4872200.0,  0.09950},
    {"Propane",   369.830,  4251200.0,  0.15230},
    {"n-Butane",  425.125,  3796000.0,  0.20020},
    {"n-Pentane", 469.700,  3370000.0,  0.25150},
    {"n-Hexane",  507.820,  3034000.0,  0.30130},
    {"Nitrogen",  126.192,  3395800.0,  0.03720},
    {"CO2",       304.128,  7377300.0,  0.22394},
    {"n-Decane",  617.700,  2103000.0,  0.48840},
};
static const int N_DB = 9;

int find_comp(const std::string& name) {
    for (int i = 0; i < N_DB; i++)
        if (name == COMP_DB[i].name) return i;
    return -1;
}

// ---------- EOS parameter computation ----------

// Compute a_i*alpha_i(T) and b_i for each component at temperature T
void compute_eos_params(const int* ids, int nc, double T,
                        double* a_alpha, double* b_param) {
    for (int i = 0; i < nc; i++) {
        const Component& c = COMP_DB[ids[i]];

        // Attractive parameter constant (Eq. 4)
        double a0 = 0.42748023 * R_GAS * R_GAS * c.Tc * c.Tc / c.Pc;

        // Acentric-factor correlation for m_ii (Table 1)
        double m = 0.480 + 1.574 * c.omega - 0.176 * c.omega * c.omega;

        // Soave-type alpha function
        double sqrtTr = std::sqrt(T / c.Tc);
        double alpha = (1.0 + m * (1.0 - sqrtTr)) * (1.0 + m * (1.0 - sqrtTr));

        a_alpha[i] = a0 * alpha;
        b_param[i] = 0.07780 * R_GAS * c.Tc / c.Pc;
    }
}

// Van der Waals one-fluid mixing rules (kij = 0 for all pairs)
void mix_params(const double* a, const double* b, const double* x,
                int nc, double* am, double* bm, double* aij_out) {
    *am = 0.0;
    *bm = 0.0;
    for (int i = 0; i < nc; i++) {
        *bm += x[i] * b[i];
        for (int j = 0; j < nc; j++) {
            double aij = std::sqrt(a[i] * a[j]);
            if (aij_out) aij_out[i * nc + j] = aij;
            *am += x[i] * x[j] * aij;
        }
    }
}

// ---------- Cubic equation solver ----------

// Solve cubic t³ + p2·t² + p1·t + p0 = 0 via Cardano's method
// Returns number of real roots (1 or 3), stored in roots[] ascending
int solve_cubic(double p2, double p1, double p0, double* roots) {
    double Q = (3.0 * p1 - p2 * p2) / 9.0;
    double R = (9.0 * p2 * p1 - 27.0 * p0 - 2.0 * p2 * p2 * p2) / 54.0;
    double D = Q * Q * Q + R * R;

    int nr = 0;
    if (D > 1e-30) {
        double sqD = std::sqrt(D);
        double S = std::cbrt(R + sqD);
        double U = std::cbrt(R - sqD);
        roots[nr++] = S + U - p2 / 3.0;
    } else {
        double mQ = std::max(-Q, 0.0);
        double rQ = std::sqrt(mQ);
        double mQ3 = std::max(-Q * Q * Q, 0.0);
        double theta = 0.0;
        if (mQ3 > 1e-30) {
            double ca = std::max(-1.0, std::min(1.0, R / std::sqrt(mQ3)));
            theta = std::acos(ca);
        }
        roots[nr++] = 2.0 * rQ * std::cos(theta / 3.0) - p2 / 3.0;
        roots[nr++] = 2.0 * rQ * std::cos((theta + 2.0 * M_PI) / 3.0) - p2 / 3.0;
        roots[nr++] = 2.0 * rQ * std::cos((theta + 4.0 * M_PI) / 3.0) - p2 / 3.0;
    }

    // Sort ascending
    for (int i = 0; i < nr; i++)
        for (int j = i + 1; j < nr; j++)
            if (roots[j] < roots[i]) std::swap(roots[i], roots[j]);
    return nr;
}

// Compressibility factor Z from dimensionless EOS parameters A, B
double get_Z(double A, double B, bool vapor_phase) {
    // PR EOS cubic: Z³ + c2·Z² + c1·Z + c0 = 0
    double c2 = -(1.0 + B);
    double c1 = A;
    double c0 = -A * B;

    double roots[3];
    int nr = solve_cubic(c2, c1, c0, roots);

    // Keep roots satisfying Z > B (physical constraint: molar volume > covolume)
    double valid[3];
    int nv = 0;
    for (int i = 0; i < nr; i++)
        if (roots[i] > B + 1e-12)
            valid[nv++] = roots[i];

    if (nv == 0) return B + 0.001;          // Fallback
    return vapor_phase ? valid[nv - 1] : valid[0];
}

// ---------- Fugacity coefficients ----------

void compute_ln_phi(const double* a, const double* b, const double* x,
                    int nc, double am, double bm, const double* aij,
                    double Z, double T, double P, double* ln_phi) {
    double A = am * P / (R_GAS * R_GAS * T * T);
    double B = bm * P / (R_GAS * T);

    double D1 = 1.0 + SQRT2;   // Delta_1 for PR
    double D2 = 1.0 - SQRT2;   // Delta_2 for PR

    double log_ratio = std::log((Z + D1 * B) / (Z + D2 * B));

    for (int i = 0; i < nc; i++) {
        double sum_xj_aij = 0.0;
        for (int j = 0; j < nc; j++)
            sum_xj_aij += x[j] * aij[i * nc + j];

        double bi_bm = b[i] / bm;

        // Partial molar contribution: (∂(n·am)/∂ni) / am
        double mix_deriv = sum_xj_aij / am - bi_bm;

        ln_phi[i] = bi_bm * (Z - 1.0)
                    - std::log(std::max(Z - B, 1e-15))
                    - A / (2.0 * SQRT2 * B) * mix_deriv * log_ratio;
    }
}

// ---------- Wilson K-value initialization ----------

void wilson_K(const int* ids, int nc, double T, double P, double* K) {
    for (int i = 0; i < nc; i++) {
        const Component& c = COMP_DB[ids[i]];
        K[i] = (c.Pc / P) * std::exp(5.373 * (1.0 + c.omega) * (1.0 - c.Tc / T));
    }
}

// ---------- Rachford-Rice ----------

double rr_func(const double* z, const double* K, int nc, double beta) {
    double f = 0.0;
    for (int i = 0; i < nc; i++)
        f += z[i] * (K[i] - 1.0) / (1.0 + beta * (K[i] - 1.0));
    return f;
}

double solve_rr(const double* z, const double* K, int nc) {
    double lo = 0.0, hi = 1.0;
    for (int i = 0; i < nc; i++) {
        if (K[i] > 1.0 + 1e-15)
            lo = std::max(lo, -1.0 / (K[i] - 1.0) + 1e-10);
        else if (K[i] < 1.0 - 1e-15)
            hi = std::min(hi, 1.0 / (1.0 - K[i]) - 1e-10);
    }
    lo = std::max(lo, 1e-10);
    hi = std::min(hi, 1.0 - 1e-10);
    if (lo >= hi) return -1.0;

    double flo = rr_func(z, K, nc, lo);
    double fhi = rr_func(z, K, nc, hi);
    if (flo * fhi > 0.0) return -1.0;   // No sign change → single phase

    for (int iter = 0; iter < 200; iter++) {
        double mid = 0.5 * (lo + hi);
        double fm = rr_func(z, K, nc, mid);
        if (std::abs(fm) < 1e-14) return mid;
        if (flo * fm < 0.0) { hi = mid; fhi = fm; }
        else                 { lo = mid; flo = fm; }
    }
    return 0.5 * (lo + hi);
}

// ---------- Isothermal flash ----------

struct FlashResult {
    std::string phase;
    double beta;
    std::vector<double> x, y;
    double fug_residual;
    bool converged;
};

FlashResult run_flash(const int* ids, const double* z, int nc,
                      double T, double P) {
    FlashResult res;
    res.x.resize(nc);
    res.y.resize(nc);
    res.converged = false;

    double K[20], a[20], b[20], aij[400];

    // Wilson initialization
    wilson_K(ids, nc, T, P, K);

    double beta = solve_rr(z, K, nc);
    if (beta < 0.0 || beta > 1.0) {
        res.phase = "single-phase";
        res.beta = -1.0;
        for (int i = 0; i < nc; i++) { res.x[i] = z[i]; res.y[i] = z[i]; }
        res.fug_residual = 0.0;
        res.converged = true;
        return res;
    }

    // Successive substitution
    for (int iter = 0; iter < 500; iter++) {
        // Phase compositions from current K and beta
        for (int i = 0; i < nc; i++) {
            res.x[i] = z[i] / (1.0 + beta * (K[i] - 1.0));
            res.y[i] = K[i] * res.x[i];
        }
        double sx = 0.0, sy = 0.0;
        for (int i = 0; i < nc; i++) { sx += res.x[i]; sy += res.y[i]; }
        for (int i = 0; i < nc; i++) { res.x[i] /= sx; res.y[i] /= sy; }

        // EOS for both phases
        compute_eos_params(ids, nc, T, a, b);

        double am_L, bm_L;
        mix_params(a, b, res.x.data(), nc, &am_L, &bm_L, aij);
        double A_L = am_L * P / (R_GAS * R_GAS * T * T);
        double B_L = bm_L * P / (R_GAS * T);
        double Z_L = get_Z(A_L, B_L, false);
        double ln_phi_L[20];
        compute_ln_phi(a, b, res.x.data(), nc, am_L, bm_L, aij,
                       Z_L, T, P, ln_phi_L);

        double am_V, bm_V;
        mix_params(a, b, res.y.data(), nc, &am_V, &bm_V, aij);
        double A_V = am_V * P / (R_GAS * R_GAS * T * T);
        double B_V = bm_V * P / (R_GAS * T);
        double Z_V = get_Z(A_V, B_V, true);
        double ln_phi_V[20];
        compute_ln_phi(a, b, res.y.data(), nc, am_V, bm_V, aij,
                       Z_V, T, P, ln_phi_V);

        // Update K-values
        double max_change = 0.0;
        for (int i = 0; i < nc; i++) {
            double lnK_new = ln_phi_L[i] - ln_phi_V[i];
            double K_new = std::exp(std::max(-40.0, std::min(40.0, lnK_new)));
            if (K[i] > 1e-30)
                max_change = std::max(max_change,
                                      std::abs(std::log(K_new / K[i])));
            K[i] = K_new;
        }

        beta = solve_rr(z, K, nc);
        if (beta < 0.0 || beta > 1.0) {
            res.phase = "single-phase";
            res.beta = -1.0;
            for (int i = 0; i < nc; i++) { res.x[i] = z[i]; res.y[i] = z[i]; }
            res.fug_residual = 0.0;
            res.converged = true;
            return res;
        }

        if (max_change < 1e-10) {
            res.converged = true;
            break;
        }
    }

    // Final phase compositions
    for (int i = 0; i < nc; i++) {
        res.x[i] = z[i] / (1.0 + beta * (K[i] - 1.0));
        res.y[i] = K[i] * res.x[i];
    }
    double sx = 0.0, sy = 0.0;
    for (int i = 0; i < nc; i++) { sx += res.x[i]; sy += res.y[i]; }
    for (int i = 0; i < nc; i++) { res.x[i] /= sx; res.y[i] /= sy; }

    // Compute final fugacity residual
    compute_eos_params(ids, nc, T, a, b);
    double am_L, bm_L, am_V, bm_V;
    mix_params(a, b, res.x.data(), nc, &am_L, &bm_L, aij);
    double Z_L = get_Z(am_L * P / (R_GAS * R_GAS * T * T),
                       bm_L * P / (R_GAS * T), false);
    double ln_phi_L[20];
    compute_ln_phi(a, b, res.x.data(), nc, am_L, bm_L, aij, Z_L, T, P, ln_phi_L);

    mix_params(a, b, res.y.data(), nc, &am_V, &bm_V, aij);
    double Z_V = get_Z(am_V * P / (R_GAS * R_GAS * T * T),
                       bm_V * P / (R_GAS * T), true);
    double ln_phi_V[20];
    compute_ln_phi(a, b, res.y.data(), nc, am_V, bm_V, aij, Z_V, T, P, ln_phi_V);

    res.fug_residual = 0.0;
    for (int i = 0; i < nc; i++) {
        if (res.x[i] > 1e-15 && res.y[i] > 1e-15) {
            double r = std::abs(ln_phi_L[i] + std::log(res.x[i])
                                - ln_phi_V[i] - std::log(res.y[i]));
            res.fug_residual = std::max(res.fug_residual, r);
        }
    }

    res.phase = "two-phase";
    res.beta = beta;
    return res;
}

// ---------- Main ----------

struct Problem {
    const char* name;
    std::vector<std::string> comps;
    std::vector<double> z;
    double T, P;
};

int main() {
    std::vector<Problem> probs = {
        {"natural_gas_7comp",
         {"Methane","Ethane","Propane","n-Butane","n-Pentane","n-Hexane","Nitrogen"},
         {0.9430, 0.0270, 0.0074, 0.0049, 0.0027, 0.0010, 0.0140},
         190.0, 4.0e6},

        {"ch4_co2_binary",
         {"Methane","CO2"},
         {0.5, 0.5},
         220.0, 3.0e6},

        {"ch4_c10_wide",
         {"Methane","n-Decane"},
         {0.7, 0.3},
         350.0, 5.0e6},

        {"ch4_c2h6_gas",
         {"Methane","Ethane"},
         {0.5, 0.5},
         300.0, 1.0e5},

        {"ternary_ch4_c2h6_co2",
         {"Methane","Ethane","CO2"},
         {0.3, 0.3, 0.4},
         220.0, 2.0e6},

        {"ch4_c3h8_binary",
         {"Methane","Propane"},
         {0.6, 0.4},
         250.0, 3.0e6},
    };

    FILE* fout = fopen("/app/results.txt", "w");
    if (!fout) {
        fprintf(stderr, "Cannot open /app/results.txt\n");
        return 1;
    }

    for (const auto& prob : probs) {
        int nc = (int)prob.comps.size();
        int ids[20];
        for (int i = 0; i < nc; i++) {
            ids[i] = find_comp(prob.comps[i]);
            if (ids[i] < 0) {
                fprintf(stderr, "Unknown component: %s\n", prob.comps[i].c_str());
                fclose(fout);
                return 1;
            }
        }

        FlashResult r = run_flash(ids, prob.z.data(), nc, prob.T, prob.P);

        fprintf(fout, "=== %s ===\n", prob.name);
        fprintf(fout, "phase: %s\n", r.phase.c_str());
        fprintf(fout, "beta: %.15e\n", r.beta);
        fprintf(fout, "converged: %s\n", r.converged ? "true" : "false");
        fprintf(fout, "fug_residual: %.15e\n", r.fug_residual);
        fprintf(fout, "x:");
        for (int i = 0; i < nc; i++) fprintf(fout, " %.15e", r.x[i]);
        fprintf(fout, "\n");
        fprintf(fout, "y:");
        for (int i = 0; i < nc; i++) fprintf(fout, " %.15e", r.y[i]);
        fprintf(fout, "\n\n");
    }

    fclose(fout);
    fprintf(stdout, "Results written to /app/results.txt\n");
    return 0;
}
