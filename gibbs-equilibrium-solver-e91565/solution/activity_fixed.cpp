#include "activity.hpp"
#include <cmath>
#include <algorithm>

// FIXED activity coefficient module:
//   1. Correct interpolation formula (divide by interval width)
//   2. Implemented B-dot extended Debye-Huckel model
//

static const int N_TABLE = 5;
static const double T_TAB[N_TABLE]    = {273.15, 298.15, 323.15, 348.15, 373.15};
static const double A_TAB[N_TABLE]    = {0.4913, 0.5085, 0.5340, 0.5639, 0.5998};
static const double B_TAB[N_TABLE]    = {0.3247, 0.3281, 0.3346, 0.3421, 0.3510};
static const double BDOT_TAB[N_TABLE] = {0.0394, 0.0410, 0.0438, 0.0470, 0.0500};

static double interp(const double T_tab[], const double V_tab[], int n, double T)
{
    if (T <= T_tab[0])   return V_tab[0];
    if (T >= T_tab[n-1]) return V_tab[n-1];
    for (int i = 0; i < n - 1; ++i) {
        if (T <= T_tab[i + 1]) {
            // FIX: correct linear interpolation with normalization
            double frac = (T - T_tab[i]) / (T_tab[i + 1] - T_tab[i]);
            return V_tab[i] + frac * (V_tab[i + 1] - V_tab[i]);
        }
    }
    return V_tab[n - 1];
}

double debye_huckel_A(double T) { return interp(T_TAB, A_TAB, N_TABLE, T); }
double debye_huckel_B(double T) { return interp(T_TAB, B_TAB, N_TABLE, T); }
double bdot_param(double T)     { return interp(T_TAB, BDOT_TAB, N_TABLE, T); }

double bdot_log10_gamma(int z, double ion_size_a, double I, double T)
{
    if (z == 0) return 0.0;
    // FIX: implemented B-dot extended Debye-Huckel
    double A  = debye_huckel_A(T);
    double B  = debye_huckel_B(T);
    double bd = bdot_param(T);
    double sI = std::sqrt(std::max(I, 0.0));
    return -A * z * z * sI / (1.0 + ion_size_a * B * sI) + bd * I;
}

double compute_ionic_strength(const double mol[], const int charges[], int n)
{
    double I = 0.0;
    for (int i = 0; i < n; ++i) {
        if (charges[i] == 0) continue;
        I += mol[i] * charges[i] * charges[i];
    }
    return 0.5 * I;
}
