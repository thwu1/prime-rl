// CORRECTED aqueous geochemistry equilibrium solver
// All four bugs from the original have been fixed:
//   1. Ionic strength: uses z*z instead of abs(z)
//   2. Davies equation: correct negative sign
//   3. Convergence tolerance: 1e-12 instead of 1e-3
//   4. CO3-- dissociation: uses LK_A2 instead of LK_A1
//

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <algorithm>
#include <iostream>

static const double R_GAS      = 8.314462;
static const double LN10       = 2.302585093;
static const double A_DAVIES   = 0.5085;

enum Species {
    SP_H2O = 0, SP_H, SP_OH, SP_NA, SP_CL, SP_CA,
    SP_CO2, SP_HCO3, SP_CO3, SP_CACO3AQ, SP_NACLAQ,
    NUM_SPECIES
};

static const int CHARGE[NUM_SPECIES] = {
    0, 1, -1, 1, -1, 2, 0, -1, -2, 0, 0
};

enum Primary {
    PR_H = 0, PR_NA, PR_CL, PR_CA, PR_CO2,
    NUM_PRIMARY
};

enum LogKIdx {
    LK_W = 0, LK_A1, LK_A2, LK_CACO3, LK_NACL, LK_SP_CALCITE,
    NUM_LK
};

static const double LK[NUM_LK] = {
    -13.991, -6.343, -10.326, 3.326, -0.777, -8.478
};

struct Problem {
    double T;
    double total_Na, total_Cl, total_Ca, total_C;
};

struct Result {
    double pH, ionic_strength;
    double m[NUM_SPECIES];
    double charge_balance, calcite_SI;
    bool   converged;
    int    iterations;
};

// FIX 1: use z[i]*z[i] (charge squared) instead of abs(z[i])
static double compute_I(const double mol[], const int z[], int n)
{
    double I = 0.0;
    for (int i = 0; i < n; ++i) {
        if (z[i] == 0) continue;
        I += mol[i] * z[i] * z[i];              // FIXED: z^2
    }
    return 0.5 * I;
}

// FIX 2: correct negative sign in Davies equation
static double log10_gamma(int z, double I)
{
    if (z == 0) return 0.0;
    double sI = std::sqrt(std::max(I, 0.0));
    return -A_DAVIES * z * z * (sI / (1.0 + sI) - 0.3 * I);   // FIXED: minus sign
}

static void compute_secondary(const double basis[], double I, double m[])
{
    double mH   = basis[PR_H];
    double mNa  = basis[PR_NA];
    double mCl  = basis[PR_CL];
    double mCa  = basis[PR_CA];
    double mCO2 = basis[PR_CO2];

    double lg[NUM_SPECIES];
    for (int i = 0; i < NUM_SPECIES; ++i)
        lg[i] = log10_gamma(CHARGE[i], I);

    m[SP_H2O] = 1.0;
    m[SP_H]   = mH;
    m[SP_NA]  = mNa;
    m[SP_CL]  = mCl;
    m[SP_CA]  = mCa;
    m[SP_CO2] = mCO2;

    double log_mOH = LK[LK_W] - std::log10(mH) - lg[SP_H] - lg[SP_OH];
    m[SP_OH] = std::pow(10.0, log_mOH);

    double log_mHCO3 = LK[LK_A1]
                     + std::log10(mCO2) + lg[SP_CO2]
                     - std::log10(mH)   - lg[SP_H]
                     - lg[SP_HCO3];
    m[SP_HCO3] = std::pow(10.0, log_mHCO3);

    // FIX 4: use LK_A2 (second dissociation) not LK_A1
    double log_mCO3 = LK[LK_A2] + log_mHCO3 + lg[SP_HCO3]
                    - std::log10(mH) - lg[SP_H]
                    - lg[SP_CO3];
    m[SP_CO3] = std::pow(10.0, log_mCO3);

    double log_mCaCO3 = LK[LK_CACO3]
                      + std::log10(mCa)       + lg[SP_CA]
                      + std::log10(m[SP_CO3]) + lg[SP_CO3]
                      - lg[SP_CACO3AQ];
    m[SP_CACO3AQ] = std::pow(10.0, log_mCaCO3);

    double log_mNaCl = LK[LK_NACL]
                     + std::log10(mNa) + lg[SP_NA]
                     + std::log10(mCl) + lg[SP_CL]
                     - lg[SP_NACLAQ];
    m[SP_NACLAQ] = std::pow(10.0, log_mNaCl);
}

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

static void eval_residual(const Problem& p, const double x[], double F[],
                          double mout[], double& Iout)
{
    double basis[NUM_PRIMARY];
    for (int i = 0; i < NUM_PRIMARY; ++i)
        basis[i] = std::pow(10.0, x[i]);

    double I = 0.01;
    for (int k = 0; k < 20; ++k) {
        compute_secondary(basis, I, mout);
        I = compute_I(mout + 1, CHARGE + 1, NUM_SPECIES - 1);
    }
    Iout = I;

    F[0] = 0.0;
    for (int i = 1; i < NUM_SPECIES; ++i)
        F[0] += CHARGE[i] * mout[i];

    F[1] = mout[SP_NA] + mout[SP_NACLAQ] - p.total_Na;
    F[2] = mout[SP_CL] + mout[SP_NACLAQ] - p.total_Cl;
    F[3] = mout[SP_CA] + mout[SP_CACO3AQ] - p.total_Ca;
    F[4] = mout[SP_CO2] + mout[SP_HCO3] + mout[SP_CO3]
         + mout[SP_CACO3AQ] - p.total_C;
}

static Result solve(const Problem& p)
{
    Result res;
    res.converged  = false;
    res.iterations = 0;

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

        // FIX 3: tight convergence tolerance
        if (maxF < 1e-12) {
            res.converged = true;
            break;
        }

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

        for (int i = 0; i < NUM_PRIMARY; ++i)
            J[i][NUM_PRIMARY] = -F[i];

        double dx[NUM_PRIMARY];
        if (!gauss_solve(J, dx, NUM_PRIMARY)) {
            for (int i = 0; i < NUM_PRIMARY; ++i) x[i] += 0.01;
            continue;
        }

        double alpha = 1.0;
        for (int i = 0; i < NUM_PRIMARY; ++i)
            if (std::abs(dx[i]) > 1.5)
                alpha = std::min(alpha, 1.5 / std::abs(dx[i]));

        for (int i = 0; i < NUM_PRIMARY; ++i)
            x[i] += alpha * dx[i];
    }

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

    double lgCa  = log10_gamma(CHARGE[SP_CA],  I);
    double lgCO3 = log10_gamma(CHARGE[SP_CO3], I);
    res.calcite_SI = std::log10(res.m[SP_CA])  + lgCa
                   + std::log10(res.m[SP_CO3]) + lgCO3
                   - LK[LK_SP_CALCITE];
    return res;
}

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
