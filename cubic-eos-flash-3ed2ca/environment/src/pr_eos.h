#pragma once

#include "component_db.h"
#include <vector>
#include <cmath>

const double R_GAS = 8.314462618;  // J/(mol*K)
const double SQRT2 = 1.4142135623730951;

// Peng-Robinson pure-component parameter functions
double pr_m(double omega);
double pr_alpha(double T, double Tc, double omega);
double pr_ai(const Component& c, double T);
double pr_bi(const Component& c);

// Cubic equation solver: returns valid Z roots sorted ascending
std::vector<double> solve_cubic(double A, double B);

// Fugacity coefficients ln(phi_i) via Peng-Robinson mixing rules
// want_liquid: true selects smallest Z root, false selects largest
// Z_out receives the selected compressibility factor
std::vector<double> ln_fugacity_coefficients(
    const std::vector<double>& x,
    const std::vector<double>& ai,
    const std::vector<double>& bi,
    const std::vector<int>& comp_idx,
    double T, double P,
    bool want_liquid,
    double& Z_out);
