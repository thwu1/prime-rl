// Aqueous geochemistry equilibrium solver
// Computes speciation for H2O-Na-Cl-Ca-C systems at 25 deg C via
// Newton-Raphson on mass/charge balance with Davies activity model.
//

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <algorithm>
#include <iostream>

// ---------------------------------------------------------------------------
// Physical / thermodynamic constants
// ---------------------------------------------------------------------------
static const double R_GAS      = 8.314462;       // J mol-1 K-1
static const double LN10       = 2.302585093;
static const double A_DAVIES   = 0.5085;         // Debye-Huckel A at 25 C

// ---------------------------------------------------------------------------
// Species indices
// ---------------------------------------------------------------------------
enum Species {
    SP_H2O = 0, SP_H, SP_OH, SP_NA, SP_CL, SP_CA,
    SP_CO2, SP_HCO3, SP_CO3, SP_CACO3AQ, SP_NACLAQ,
    NUM_SPECIES
};

// Ionic charges of each species (same order as enum)
static const int CHARGE[NUM_SPECIES] = {
    0,    // H2O
    1,    // H+
   -1,    // OH-
    1,    // Na+
   -1,    // Cl-
    2,    // Ca2+
    0,    // CO2(aq)
   -1,    // HCO3-
   -2,    // CO3--
    0,    // CaCO3(aq)
    0     // NaCl(aq)
};

// ---------------------------------------------------------------------------
// Primary (basis) species whose log10-molalities are the unknowns
// ---------------------------------------------------------------------------
enum Primary {
    PR_H = 0, PR_NA, PR_CL, PR_CA, PR_CO2,
    NUM_PRIMARY
};

// ---------------------------------------------------------------------------
// Equilibrium constants  (log10 K at 25 C, 1 atm)
// Derived from SUPCRT standard Gibbs energies (J mol-1):
//   H2O  -237181.72    H+  0.00         OH-  -157297.48
//   Na+  -261880.74    Cl- -131289.74   Ca++ -552790.08
//   CO2  -385974.00    HCO3- -586939.89 CO3-- -527983.14
//   CaCO3(aq) -1099764.40   NaCl(aq) -388735.44
//   Calcite   -1129177.92   Halite   -384120.49
// ---------------------------------------------------------------------------
enum LogKIdx {
    LK_W = 0,           // H2O  = H+  + OH-
    LK_A1,              // CO2  + H2O = H+  + HCO3-
    LK_A2,              // HCO3-      = H+  + CO3--
    LK_CACO3,           // Ca++ + CO3-- = CaCO3(aq)
    LK_NACL,            // Na+  + Cl-   = NaCl(aq)
    LK_SP_CALCITE,      // CaCO3(s) = Ca++ + CO3--
    NUM_LK
};

static const double LK[NUM_LK] = {
    -13.991,   // LK_W
     -6.343,   // LK_A1
    -10.326,   // LK_A2
      3.326,   // LK_CACO3
     -0.777,   // LK_NACL
     -8.478    // LK_SP_CALCITE
};

// ---------------------------------------------------------------------------
// Problem / result data
// ---------------------------------------------------------------------------
struct Problem {
    double T;            // temperature (K)
    double total_Na;     // total Na  (mol kg-1 water)
    double total_Cl;     // total Cl  (mol kg-1 water)
    double total_Ca;     // total Ca  (mol kg-1 water)
    double total_C;      // total inorganic C (mol kg-1 water)
};

struct Result {
    double pH;
    double ionic_strength;
    double m[NUM_SPECIES];
    double charge_balance;
    double calcite_SI;
    bool   converged;
    int    iterations;
};

// ---------------------------------------------------------------------------
// Ionic strength  I = 0.5 * sum_i( m_i * z_i^2 )
// Arguments: arrays of molalities and charges for the charged solute species.
// ---------------------------------------------------------------------------
static double compute_I(const double mol[], const int z[], int n)
{
    double I = 0.0;
    for (int i = 0; i < n; ++i) {
        if (z[i] == 0) continue;
        I += mol[i] * std::abs(z[i]);           // z_i^2 contribution
    }
    return 0.5 * I;
}

// ---------------------------------------------------------------------------
// Davies equation for single-ion activity coefficient
//   log10(gamma) = -A * z^2 * ( sqrt(I)/(1+sqrt(I)) - 0.3*I )
// ---------------------------------------------------------------------------
static double log10_gamma(int z, double I)
{
    if (z == 0) return 0.0;
    double sI = std::sqrt(std::max(I, 0.0));
    // Davies formula with Debye-Huckel A parameter
    return A_DAVIES * z * z * (sI / (1.0 + sI) - 0.3 * I);
}

// ---------------------------------------------------------------------------
// Compute secondary (non-basis) species from basis molalities and I
// ---------------------------------------------------------------------------
static void compute_secondary(const double basis[], double I, double m[])
{
    double mH   = basis[PR_H];
    double mNa  = basis[PR_NA];
    double mCl  = basis[PR_CL];
    double mCa  = basis[PR_CA];
    double mCO2 = basis[PR_CO2];

    // Activity coefficients
    double lg[NUM_SPECIES];
    for (int i = 0; i < NUM_SPECIES; ++i)
        lg[i] = log10_gamma(CHARGE[i], I);

    // Copy basis species into the full array
    m[SP_H2O] = 1.0;
    m[SP_H]   = mH;
    m[SP_NA]  = mNa;
    m[SP_CL]  = mCl;
    m[SP_CA]  = mCa;
    m[SP_CO2] = mCO2;

    // --- OH-  via water dissociation  K_w = (a_H+)(a_OH-) ---
    double log_mOH = LK[LK_W] - std::log10(mH) - lg[SP_H] - lg[SP_OH];
    m[SP_OH] = std::pow(10.0, log_mOH);

    // --- HCO3-  via 1st carbonic acid dissoc.  K_a1 = (a_H+)(a_HCO3-) / a_CO2 ---
    double log_mHCO3 = LK[LK_A1]
                     + std::log10(mCO2) + lg[SP_CO2]
                     - std::log10(mH)   - lg[SP_H]
                     - lg[SP_HCO3];
    m[SP_HCO3] = std::pow(10.0, log_mHCO3);

    // --- CO3--  via 2nd dissociation  K_a2 = (a_H+)(a_CO3--) / a_HCO3- ---
    double log_mCO3 = LK[LK_A1] + log_mHCO3 + lg[SP_HCO3]
                    - std::log10(mH) - lg[SP_H]
                    - lg[SP_CO3];
    m[SP_CO3] = std::pow(10.0, log_mCO3);

    // --- CaCO3(aq) complexation  K = a_CaCO3 / (a_Ca * a_CO3) ---
    double log_mCaCO3 = LK[LK_CACO3]
                      + std::log10(mCa)     + lg[SP_CA]
                      + std::log10(m[SP_CO3]) + lg[SP_CO3]
                      - lg[SP_CACO3AQ];
    m[SP_CACO3AQ] = std::pow(10.0, log_mCaCO3);

    // --- NaCl(aq) ion pairing  K = a_NaCl / (a_Na * a_Cl) ---
    double log_mNaCl = LK[LK_NACL]
                     + std::log10(mNa) + lg[SP_NA]
                     + std::log10(mCl) + lg[SP_CL]
                     - lg[SP_NACLAQ];
    m[SP_NACLAQ] = std::pow(10.0, log_mNaCl);
}

// ---------------------------------------------------------------------------
// I/O helpers
// ---------------------------------------------------------------------------
static Problem read_problem(const char* path)
{
    Problem p = {298.15, 0.0, 0.0, 0.0, 0.0};
    std::ifstream f(path);
    if (!f) { std::fprintf(stderr, "Cannot open %s\n", path); std::exit(2); }
    std::string key; double val;
    while (f >> key >> val) {
        if      (key == "temperature") p.T        = val;
        else if (key == "total_Na")    p.total_Na = val;
        else if (key == "total_Cl")    p.total_Cl = val;
        else if (key == "total_Ca")    p.total_Ca = val;
        else if (key == "total_C")     p.total_C  = val;
    }
    return p;
}

static void write_result(const char* path, const Result& r)
{
    FILE* f = std::fopen(path, "w");
    if (!f) { std::fprintf(stderr, "Cannot write %s\n", path); std::exit(2); }
    std::fprintf(f, "pH %.15e\n",              r.pH);
    std::fprintf(f, "ionic_strength %.15e\n",  r.ionic_strength);
    std::fprintf(f, "m_H %.15e\n",             r.m[SP_H]);
    std::fprintf(f, "m_OH %.15e\n",            r.m[SP_OH]);
    std::fprintf(f, "m_Na %.15e\n",            r.m[SP_NA]);
    std::fprintf(f, "m_Cl %.15e\n",            r.m[SP_CL]);
    std::fprintf(f, "m_Ca %.15e\n",            r.m[SP_CA]);
    std::fprintf(f, "m_CO2 %.15e\n",           r.m[SP_CO2]);
    std::fprintf(f, "m_HCO3 %.15e\n",         r.m[SP_HCO3]);
    std::fprintf(f, "m_CO3 %.15e\n",           r.m[SP_CO3]);
    std::fprintf(f, "m_CaCO3aq %.15e\n",       r.m[SP_CACO3AQ]);
    std::fprintf(f, "m_NaClaq %.15e\n",        r.m[SP_NACLAQ]);
    std::fprintf(f, "charge_balance %.15e\n",  r.charge_balance);
    std::fprintf(f, "calcite_SI %.15e\n",      r.calcite_SI);
    std::fprintf(f, "converged %d\n",          r.converged ? 1 : 0);
    std::fprintf(f, "iterations %d\n",         r.iterations);
    std::fclose(f);
}

// ---------------------------------------------------------------------------
// Gaussian elimination  (N x N augmented system  [A|b] -> x)
// ---------------------------------------------------------------------------
static bool gauss_solve(double A[][NUM_PRIMARY + 1], double x[], int n)
{
    for (int k = 0; k < n; ++k) {
        int piv = k;
        for (int i = k + 1; i < n; ++i)
            if (std::abs(A[i][k]) > std::abs(A[piv][k])) piv = i;
        if (piv != k)
            for (int j = 0; j <= n; ++j) std::swap(A[k][j], A[piv][j]);
        if (std::abs(A[k][k]) < 1e-40) return false;
        for (int i = k + 1; i < n; ++i) {
            double f = A[i][k] / A[k][k];
            for (int j = k; j <= n; ++j) A[i][j] -= f * A[k][j];
        }
    }
    for (int i = n - 1; i >= 0; --i) {
        x[i] = A[i][n];
        for (int j = i + 1; j < n; ++j) x[i] -= A[i][j] * x[j];
        x[i] /= A[i][i];
    }
    return true;
}

// ---------------------------------------------------------------------------
// Evaluate residual vector  F(x)  where x_i = log10(m_basis_i)
//
//   F[0]  charge balance           sum_i z_i * m_i = 0
//   F[1]  Na  mass balance         m_Na + m_NaCl(aq) = total_Na
//   F[2]  Cl  mass balance         m_Cl + m_NaCl(aq) = total_Cl
//   F[3]  Ca  mass balance         m_Ca + m_CaCO3(aq) = total_Ca
//   F[4]  C   mass balance         m_CO2+m_HCO3+m_CO3+m_CaCO3(aq)=total_C
// ---------------------------------------------------------------------------
static void eval_residual(const Problem& p, const double x[], double F[],
                          double mout[], double& Iout)
{
    double basis[NUM_PRIMARY];
    for (int i = 0; i < NUM_PRIMARY; ++i)
        basis[i] = std::pow(10.0, x[i]);

    // Self-consistent ionic-strength loop
    double I = 0.01;
    for (int k = 0; k < 20; ++k) {
        compute_secondary(basis, I, mout);
        I = compute_I(mout + 1, CHARGE + 1, NUM_SPECIES - 1);
    }
    Iout = I;

    // Charge balance
    F[0] = 0.0;
    for (int i = 1; i < NUM_SPECIES; ++i)
        F[0] += CHARGE[i] * mout[i];

    // Na balance
    F[1] = mout[SP_NA] + mout[SP_NACLAQ] - p.total_Na;
    // Cl balance
    F[2] = mout[SP_CL] + mout[SP_NACLAQ] - p.total_Cl;
    // Ca balance
    F[3] = mout[SP_CA] + mout[SP_CACO3AQ] - p.total_Ca;
    // C  balance
    F[4] = mout[SP_CO2] + mout[SP_HCO3] + mout[SP_CO3]
         + mout[SP_CACO3AQ] - p.total_C;
}

// ---------------------------------------------------------------------------
// Solver
// ---------------------------------------------------------------------------
static Result solve(const Problem& p)
{
    Result res;
    res.converged  = false;
    res.iterations = 0;

    // Initial guesses  (log10 molality)
    double x[NUM_PRIMARY];
    x[PR_H]   = -7.0;
    x[PR_NA]  = std::log10(std::max(p.total_Na, 1e-20));
    x[PR_CL]  = std::log10(std::max(p.total_Cl, 1e-20));
    x[PR_CA]  = std::log10(std::max(p.total_Ca, 1e-20));
    x[PR_CO2] = std::log10(std::max(p.total_C,  1e-20));

    double F[NUM_PRIMARY], Fp[NUM_PRIMARY];
    double m_tmp[NUM_SPECIES];
    double I_tmp;

    for (int iter = 0; iter < 500; ++iter) {
        res.iterations = iter + 1;
        eval_residual(p, x, F, m_tmp, I_tmp);

        double maxF = 0.0;
        for (int i = 0; i < NUM_PRIMARY; ++i)
            maxF = std::max(maxF, std::abs(F[i]));

        if (maxF < 1e-3) {                       // convergence check
            res.converged = true;
            break;
        }

        // Numerical Jacobian  (forward finite differences)
        double J[NUM_PRIMARY][NUM_PRIMARY + 1];
        const double h = 1e-7;
        for (int j = 0; j < NUM_PRIMARY; ++j) {
            double sav = x[j];
            x[j] += h;
            double m2[NUM_SPECIES]; double I2;
            eval_residual(p, x, Fp, m2, I2);
            for (int i = 0; i < NUM_PRIMARY; ++i)
                J[i][j] = (Fp[i] - F[i]) / h;
            x[j] = sav;
        }

        // Augment with -F
        for (int i = 0; i < NUM_PRIMARY; ++i)
            J[i][NUM_PRIMARY] = -F[i];

        double dx[NUM_PRIMARY];
        if (!gauss_solve(J, dx, NUM_PRIMARY)) {
            for (int i = 0; i < NUM_PRIMARY; ++i) x[i] += 0.01;
            continue;
        }

        // Damped step
        double alpha = 1.0;
        for (int i = 0; i < NUM_PRIMARY; ++i)
            if (std::abs(dx[i]) > 1.5)
                alpha = std::min(alpha, 1.5 / std::abs(dx[i]));

        for (int i = 0; i < NUM_PRIMARY; ++i)
            x[i] += alpha * dx[i];
    }

    // ---- Final state ----
    double basis[NUM_PRIMARY];
    for (int i = 0; i < NUM_PRIMARY; ++i)
        basis[i] = std::pow(10.0, x[i]);

    double I = 0.01;
    for (int k = 0; k < 30; ++k) {
        compute_secondary(basis, I, res.m);
        I = compute_I(res.m + 1, CHARGE + 1, NUM_SPECIES - 1);
    }
    res.pH = -x[PR_H];
    res.ionic_strength = I;

    res.charge_balance = 0.0;
    for (int i = 1; i < NUM_SPECIES; ++i)
        res.charge_balance += CHARGE[i] * res.m[i];

    // Calcite saturation index
    double lgCa  = log10_gamma(CHARGE[SP_CA],  I);
    double lgCO3 = log10_gamma(CHARGE[SP_CO3], I);
    res.calcite_SI = std::log10(res.m[SP_CA])  + lgCa
                   + std::log10(res.m[SP_CO3]) + lgCO3
                   - LK[LK_SP_CALCITE];
    return res;
}

// ---------------------------------------------------------------------------
int main(int argc, char* argv[])
{
    const char* inp = "/app/problem_1.txt";
    const char* out = "/app/results_1.txt";
    if (argc > 1) inp = argv[1];
    if (argc > 2) out = argv[2];

    Problem p = read_problem(inp);
    Result  r = solve(p);
    write_result(out, r);

    std::printf("pH=%.4f  I=%.6f  conv=%s  iter=%d\n",
                r.pH, r.ionic_strength,
                r.converged ? "yes" : "no", r.iterations);
    return r.converged ? 0 : 1;
}
