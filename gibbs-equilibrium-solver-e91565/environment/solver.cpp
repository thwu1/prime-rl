#include "solver.hpp"
#include "activity.hpp"
#include <cmath>
#include <cstdio>
#include <algorithm>


// ---------------------------------------------------------------------------
// Compute secondary (non-basis) species from basis molalities and I
// ---------------------------------------------------------------------------
static void compute_secondary(const double basis[], double I, double T,
                               double m[])
{
    double mH   = basis[PR_H];
    double mNa  = basis[PR_NA];
    double mCl  = basis[PR_CL];
    double mCa  = basis[PR_CA];
    double mCO2 = basis[PR_CO2];
    double mSO4 = basis[PR_SO4];

    // Activity coefficients for all species
    double lg[NUM_SPECIES];
    for (int i = 0; i < NUM_SPECIES; ++i)
        lg[i] = bdot_log10_gamma(CHARGE[i], ION_SIZE[i], I, T);

    // Copy basis species
    m[SP_H]   = mH;
    m[SP_NA]  = mNa;
    m[SP_CL]  = mCl;
    m[SP_CA]  = mCa;
    m[SP_CO2] = mCO2;
    m[SP_SO4] = mSO4;

    // Temperature-dependent log K
    double lk_w     = RXDATA[RX_WATER].log_k(T);
    double lk_a1    = RXDATA[RX_A1].log_k(T);
    double lk_a2    = RXDATA[RX_A2].log_k(T);
    double lk_caco3 = RXDATA[RX_CACO3].log_k(T);
    double lk_nacl  = RXDATA[RX_NACL].log_k(T);
    double lk_caso4 = RXDATA[RX_CASO4].log_k(T);

    // OH-  via H2O = H+ + OH-
    double log_mOH = lk_w - std::log10(mH) - lg[SP_H] - lg[SP_OH];
    m[SP_OH] = std::pow(10.0, log_mOH);

    // HCO3-  via CO2 + H2O = H+ + HCO3-
    double log_mHCO3 = lk_a1 + std::log10(mCO2) + lg[SP_CO2]
                     - std::log10(mH) - lg[SP_H] - lg[SP_HCO3];
    m[SP_HCO3] = std::pow(10.0, log_mHCO3);

    // CO3--  via HCO3- = H+ + CO3--
    double log_mCO3 = lk_a2 + log_mHCO3 + lg[SP_HCO3]
                    - std::log10(mH) - lg[SP_H] - lg[SP_CO3];
    m[SP_CO3] = std::pow(10.0, log_mCO3);

    // CaCO3(aq)  via Ca++ + CO3-- = CaCO3(aq)
    double log_mCaCO3 = lk_caco3
                       + std::log10(mCa) + lg[SP_CA]
                       + std::log10(m[SP_CO3]) + lg[SP_CO3]
                       - lg[SP_CACO3AQ];
    m[SP_CACO3AQ] = std::pow(10.0, log_mCaCO3);

    // NaCl(aq)  via Na+ + Cl- = NaCl(aq)
    double log_mNaCl = lk_nacl
                     + std::log10(mNa) + lg[SP_NA]
                     + std::log10(mCl) + lg[SP_CL]
                     - lg[SP_NACLAQ];
    m[SP_NACLAQ] = std::pow(10.0, log_mNaCl);

    // CaSO4(aq)  via Ca++ + SO4-- = CaSO4(aq)
    double log_mCaSO4 = lk_caso4
                       + std::log10(mCa) + lg[SP_CA]
                       + std::log10(mSO4) + lg[SP_SO4]
                       - lg[SP_CASO4AQ];
    m[SP_CASO4AQ] = std::pow(10.0, log_mCaSO4);
}

// ---------------------------------------------------------------------------
// Gaussian elimination  (n x n+1 augmented system)
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
// Evaluate residual F(x) — aqueous speciation only, no mineral phases
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
        compute_secondary(basis, I, p.T, mout);
        I = compute_ionic_strength(mout, CHARGE, NUM_SPECIES);
    }
    Iout = I;

    // Charge balance
    F[0] = 0.0;
    for (int i = 0; i < NUM_SPECIES; ++i)
        F[0] += CHARGE[i] * mout[i];

    // Na mass balance
    F[1] = mout[SP_NA] + mout[SP_NACLAQ] - p.total_Na;
    // Cl mass balance
    F[2] = mout[SP_CL] + mout[SP_NACLAQ] - p.total_Cl;
    // Ca mass balance
    F[3] = mout[SP_CA] + mout[SP_CACO3AQ] - p.total_Ca;
    // C mass balance
    F[4] = mout[SP_CO2] + mout[SP_HCO3] + mout[SP_CO3]
         + mout[SP_CACO3AQ] - p.total_C;
    // S mass balance
    if (p.total_S > 1e-15)
        F[5] = mout[SP_SO4] - p.total_S;
    else
        F[5] = x[PR_SO4] + 20.0;  // pin SO4 to negligible value
}

// ---------------------------------------------------------------------------
// Solver — Newton-Raphson on mass/charge balance (aqueous only)
// ---------------------------------------------------------------------------
Result solve(const Problem& p)
{
    Result res = {};
    res.converged  = false;
    res.iterations = 0;
    res.n_calcite  = 0.0;
    res.n_gypsum   = 0.0;

    const int N = NUM_PRIMARY;

    // Initial guesses (log10 molality)
    double x[NUM_PRIMARY];
    x[PR_H]   = -7.0;
    x[PR_NA]  = std::log10(std::max(p.total_Na, 1e-20));
    x[PR_CL]  = std::log10(std::max(p.total_Cl, 1e-20));
    x[PR_CA]  = std::log10(std::max(p.total_Ca, 1e-20));
    x[PR_CO2] = std::log10(std::max(p.total_C,  1e-20));
    x[PR_SO4] = std::log10(std::max(p.total_S,  1e-20));

    double F[NUM_PRIMARY], Fp[NUM_PRIMARY];
    double m_tmp[NUM_SPECIES];
    double I_tmp;

    for (int iter = 0; iter < 500; ++iter) {
        res.iterations = iter + 1;
        eval_residual(p, x, F, m_tmp, I_tmp);

        double maxF = 0.0;
        for (int i = 0; i < N; ++i)
            maxF = std::max(maxF, std::abs(F[i]));

        if (maxF < 1e-3) {
            res.converged = true;
            break;
        }

        // Numerical Jacobian (forward finite differences)
        double J[NUM_PRIMARY][NUM_PRIMARY + 1];
        const double h = 0.01;

        for (int j = 0; j < N; ++j) {
            double sav = x[j];
            x[j] += h;
            double m2[NUM_SPECIES]; double I2;
            eval_residual(p, x, Fp, m2, I2);
            for (int i = 0; i < N; ++i)
                J[i][j] = (Fp[i] - F[i]) / h;
            x[j] = sav;
        }

        // Augment with -F
        for (int i = 0; i < N; ++i)
            J[i][N] = -F[i];

        double dx[NUM_PRIMARY];
        if (!gauss_solve(J, dx, N)) {
            for (int i = 0; i < N; ++i) x[i] += 0.01;
            continue;
        }

        // Damped step
        double alpha = 1.0;
        for (int i = 0; i < N; ++i)
            if (std::abs(dx[i]) > 1.5)
                alpha = std::min(alpha, 1.5 / std::abs(dx[i]));

        for (int i = 0; i < N; ++i)
            x[i] += alpha * dx[i];
    }

    // ---- Final state ----
    double basis[NUM_PRIMARY];
    for (int i = 0; i < NUM_PRIMARY; ++i)
        basis[i] = std::pow(10.0, x[i]);

    double I = 0.01;
    for (int k = 0; k < 30; ++k) {
        compute_secondary(basis, I, p.T, res.m);
        I = compute_ionic_strength(res.m, CHARGE, NUM_SPECIES);
    }
    res.pH = -x[PR_H];
    res.ionic_strength = I;

    res.charge_balance = 0.0;
    for (int i = 0; i < NUM_SPECIES; ++i)
        res.charge_balance += CHARGE[i] * res.m[i];

    // Saturation indices (informational only — no mineral logic)
    double lgCa  = bdot_log10_gamma(CHARGE[SP_CA],  ION_SIZE[SP_CA],  I, p.T);
    double lgCO3 = bdot_log10_gamma(CHARGE[SP_CO3], ION_SIZE[SP_CO3], I, p.T);
    double lgSO4 = bdot_log10_gamma(CHARGE[SP_SO4], ION_SIZE[SP_SO4], I, p.T);

    res.calcite_SI = std::log10(res.m[SP_CA])  + lgCa
                   + std::log10(res.m[SP_CO3]) + lgCO3
                   - MINDATA[MIN_CALCITE].log_k(p.T);

    if (p.total_S > 1e-15)
        res.gypsum_SI = std::log10(res.m[SP_CA])  + lgCa
                      + std::log10(res.m[SP_SO4]) + lgSO4
                      - MINDATA[MIN_GYPSUM].log_k(p.T);
    else
        res.gypsum_SI = -99.0;

    return res;
}
