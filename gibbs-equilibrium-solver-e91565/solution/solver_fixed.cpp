#include "solver.hpp"
#include "activity.hpp"
#include <cmath>
#include <cstdio>
#include <algorithm>

// FIXED solver with:
//   1. Correct mass balances (CaSO4aq included in Ca and S)
//   2. Correct Jacobian step size (1e-7)
//   3. Correct convergence tolerance (1e-10)
//   4. Mineral phase assemblage logic (calcite, gypsum)
//

static void compute_secondary(const double basis[], double I, double T,
                               double m[])
{
    double mH   = basis[PR_H];
    double mNa  = basis[PR_NA];
    double mCl  = basis[PR_CL];
    double mCa  = basis[PR_CA];
    double mCO2 = basis[PR_CO2];
    double mSO4 = basis[PR_SO4];

    double lg[NUM_SPECIES];
    for (int i = 0; i < NUM_SPECIES; ++i)
        lg[i] = bdot_log10_gamma(CHARGE[i], ION_SIZE[i], I, T);

    m[SP_H]   = mH;
    m[SP_NA]  = mNa;
    m[SP_CL]  = mCl;
    m[SP_CA]  = mCa;
    m[SP_CO2] = mCO2;
    m[SP_SO4] = mSO4;

    double lk_w     = RXDATA[RX_WATER].log_k(T);
    double lk_a1    = RXDATA[RX_A1].log_k(T);
    double lk_a2    = RXDATA[RX_A2].log_k(T);
    double lk_caco3 = RXDATA[RX_CACO3].log_k(T);
    double lk_nacl  = RXDATA[RX_NACL].log_k(T);
    double lk_caso4 = RXDATA[RX_CASO4].log_k(T);

    double log_mOH = lk_w - std::log10(mH) - lg[SP_H] - lg[SP_OH];
    m[SP_OH] = std::pow(10.0, log_mOH);

    double log_mHCO3 = lk_a1 + std::log10(mCO2) + lg[SP_CO2]
                     - std::log10(mH) - lg[SP_H] - lg[SP_HCO3];
    m[SP_HCO3] = std::pow(10.0, log_mHCO3);

    double log_mCO3 = lk_a2 + log_mHCO3 + lg[SP_HCO3]
                    - std::log10(mH) - lg[SP_H] - lg[SP_CO3];
    m[SP_CO3] = std::pow(10.0, log_mCO3);

    double log_mCaCO3 = lk_caco3
                       + std::log10(mCa) + lg[SP_CA]
                       + std::log10(m[SP_CO3]) + lg[SP_CO3]
                       - lg[SP_CACO3AQ];
    m[SP_CACO3AQ] = std::pow(10.0, log_mCaCO3);

    double log_mNaCl = lk_nacl
                     + std::log10(mNa) + lg[SP_NA]
                     + std::log10(mCl) + lg[SP_CL]
                     - lg[SP_NACLAQ];
    m[SP_NACLAQ] = std::pow(10.0, log_mNaCl);

    double log_mCaSO4 = lk_caso4
                       + std::log10(mCa) + lg[SP_CA]
                       + std::log10(mSO4) + lg[SP_SO4]
                       - lg[SP_CASO4AQ];
    m[SP_CASO4AQ] = std::pow(10.0, log_mCaSO4);
}

// Gaussian elimination on flat row-major n x (n+1) augmented matrix
static bool gauss_solve(int n, double A[], double x[])
{
    int s = n + 1;
    auto e = [&](int i, int j) -> double& { return A[i * s + j]; };

    for (int k = 0; k < n; ++k) {
        int piv = k;
        for (int i = k + 1; i < n; ++i)
            if (std::abs(e(i, k)) > std::abs(e(piv, k))) piv = i;
        if (piv != k)
            for (int j = 0; j <= n; ++j) std::swap(e(k, j), e(piv, j));
        if (std::abs(e(k, k)) < 1e-40) return false;
        for (int i = k + 1; i < n; ++i) {
            double f = e(i, k) / e(k, k);
            for (int j = k; j <= n; ++j) e(i, j) -= f * e(k, j);
        }
    }
    for (int i = n - 1; i >= 0; --i) {
        x[i] = e(i, n);
        for (int j = i + 1; j < n; ++j) x[i] -= e(i, j) * x[j];
        x[i] /= e(i, i);
    }
    return true;
}

static void eval_residual(const Problem& p, const double x[], double F[],
                          double mout[], double& Iout, int N,
                          bool cal_active, bool gyp_active)
{
    double basis[NUM_PRIMARY];
    for (int i = 0; i < NUM_PRIMARY; ++i)
        basis[i] = std::pow(10.0, x[i]);

    double n_cal = 0.0, n_gyp = 0.0;
    int idx = NUM_PRIMARY;
    if (cal_active) { n_cal = x[idx]; idx++; }
    if (gyp_active) { n_gyp = x[idx]; idx++; }

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

    // Na balance
    F[1] = mout[SP_NA] + mout[SP_NACLAQ] - p.total_Na;
    // Cl balance
    F[2] = mout[SP_CL] + mout[SP_NACLAQ] - p.total_Cl;
    // Ca balance (FIX: includes CaSO4aq and mineral amounts)
    F[3] = mout[SP_CA] + mout[SP_CACO3AQ] + mout[SP_CASO4AQ]
         + n_cal + n_gyp - p.total_Ca;
    // C balance (includes calcite)
    F[4] = mout[SP_CO2] + mout[SP_HCO3] + mout[SP_CO3]
         + mout[SP_CACO3AQ] + n_cal - p.total_C;
    // S balance (FIX: includes CaSO4aq and gypsum)
    if (p.total_S > 1e-15)
        F[5] = mout[SP_SO4] + mout[SP_CASO4AQ] + n_gyp - p.total_S;
    else
        F[5] = x[PR_SO4] + 20.0;

    // Mineral saturation constraints
    idx = NUM_PRIMARY;
    if (cal_active) {
        double lk = MINDATA[MIN_CALCITE].log_k(p.T);
        double lgCa  = bdot_log10_gamma(CHARGE[SP_CA], ION_SIZE[SP_CA], I, p.T);
        double lgCO3 = bdot_log10_gamma(CHARGE[SP_CO3], ION_SIZE[SP_CO3], I, p.T);
        F[idx] = std::log10(mout[SP_CA]) + lgCa
               + std::log10(mout[SP_CO3]) + lgCO3 - lk;
        idx++;
    }
    if (gyp_active) {
        double lk = MINDATA[MIN_GYPSUM].log_k(p.T);
        double lgCa  = bdot_log10_gamma(CHARGE[SP_CA], ION_SIZE[SP_CA], I, p.T);
        double lgSO4 = bdot_log10_gamma(CHARGE[SP_SO4], ION_SIZE[SP_SO4], I, p.T);
        F[idx] = std::log10(mout[SP_CA]) + lgCa
               + std::log10(mout[SP_SO4]) + lgSO4 - lk;
        idx++;
    }
}

Result solve(const Problem& p)
{
    Result res = {};
    res.converged  = false;
    res.iterations = 0;
    res.n_calcite  = 0.0;
    res.n_gypsum   = 0.0;

    bool cal_active = false;
    bool gyp_active = false;
    double n_cal_saved = 0.0, n_gyp_saved = 0.0;

    double x[MAX_UNKNOWNS];
    x[PR_H]   = -7.0;
    x[PR_NA]  = std::log10(std::max(p.total_Na, 1e-20));
    x[PR_CL]  = std::log10(std::max(p.total_Cl, 1e-20));
    x[PR_CA]  = std::log10(std::max(p.total_Ca, 1e-20));
    x[PR_CO2] = std::log10(std::max(p.total_C,  1e-20));
    x[PR_SO4] = std::log10(std::max(p.total_S,  1e-20));

    for (int phase_iter = 0; phase_iter < 10; ++phase_iter) {
        int N = NUM_PRIMARY;
        int cal_idx = -1, gyp_idx = -1;
        if (cal_active) {
            cal_idx = N; N++;
            x[cal_idx] = n_cal_saved > 1e-8 ? n_cal_saved : 1e-4;
        }
        if (gyp_active) {
            gyp_idx = N; N++;
            x[gyp_idx] = n_gyp_saved > 1e-8 ? n_gyp_saved : 1e-4;
        }

        double F[MAX_UNKNOWNS], Fp[MAX_UNKNOWNS];
        double m_tmp[NUM_SPECIES];
        double I_tmp;
        bool inner_conv = false;

        for (int iter = 0; iter < 500; ++iter) {
            res.iterations++;
            eval_residual(p, x, F, m_tmp, I_tmp, N, cal_active, gyp_active);

            double maxF = 0.0;
            for (int i = 0; i < N; ++i)
                maxF = std::max(maxF, std::abs(F[i]));

            if (maxF < 1e-10) {
                inner_conv = true;
                break;
            }

            // Numerical Jacobian (FIX: step = 1e-7)
            double J[MAX_UNKNOWNS * (MAX_UNKNOWNS + 1)];
            const double h = 1e-7;

            for (int j = 0; j < N; ++j) {
                double sav = x[j];
                x[j] += h;
                double m2[NUM_SPECIES]; double I2;
                eval_residual(p, x, Fp, m2, I2, N, cal_active, gyp_active);
                for (int i = 0; i < N; ++i)
                    J[i * (N + 1) + j] = (Fp[i] - F[i]) / h;
                x[j] = sav;
            }

            for (int i = 0; i < N; ++i)
                J[i * (N + 1) + N] = -F[i];

            double dx[MAX_UNKNOWNS];
            if (!gauss_solve(N, J, dx)) {
                for (int i = 0; i < NUM_PRIMARY; ++i) x[i] += 0.01;
                continue;
            }

            // Damped step
            double alpha = 1.0;
            for (int i = 0; i < NUM_PRIMARY; ++i)
                if (std::abs(dx[i]) > 1.5)
                    alpha = std::min(alpha, 1.5 / std::abs(dx[i]));

            for (int i = 0; i < N; ++i)
                x[i] += alpha * dx[i];
        }

        if (!inner_conv) break;

        // Save mineral amounts
        if (cal_active) n_cal_saved = x[cal_idx];
        if (gyp_active) n_gyp_saved = x[gyp_idx];

        // Check phase assemblage stability
        bool changed = false;

        // Check inactive minerals for supersaturation
        if (!cal_active) {
            double lk = MINDATA[MIN_CALCITE].log_k(p.T);
            double lgCa  = bdot_log10_gamma(CHARGE[SP_CA], ION_SIZE[SP_CA], I_tmp, p.T);
            double lgCO3 = bdot_log10_gamma(CHARGE[SP_CO3], ION_SIZE[SP_CO3], I_tmp, p.T);
            double SI = std::log10(m_tmp[SP_CA]) + lgCa
                      + std::log10(m_tmp[SP_CO3]) + lgCO3 - lk;
            if (SI > 0.01) {
                cal_active = true;
                n_cal_saved = 1e-4;
                changed = true;
            }
        }
        if (!gyp_active && p.total_S > 1e-15) {
            double lk = MINDATA[MIN_GYPSUM].log_k(p.T);
            double lgCa  = bdot_log10_gamma(CHARGE[SP_CA], ION_SIZE[SP_CA], I_tmp, p.T);
            double lgSO4 = bdot_log10_gamma(CHARGE[SP_SO4], ION_SIZE[SP_SO4], I_tmp, p.T);
            double SI = std::log10(m_tmp[SP_CA]) + lgCa
                      + std::log10(m_tmp[SP_SO4]) + lgSO4 - lk;
            if (SI > 0.01) {
                gyp_active = true;
                n_gyp_saved = 1e-4;
                changed = true;
            }
        }

        // Check active minerals for negative amounts (should dissolve)
        if (cal_active && n_cal_saved < -1e-8) {
            cal_active = false;
            n_cal_saved = 0.0;
            changed = true;
        }
        if (gyp_active && n_gyp_saved < -1e-8) {
            gyp_active = false;
            n_gyp_saved = 0.0;
            changed = true;
        }

        if (!changed) {
            res.converged = true;
            break;
        }
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

    res.n_calcite = cal_active ? n_cal_saved : 0.0;
    res.n_gypsum  = gyp_active ? n_gyp_saved : 0.0;

    // Saturation indices
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
