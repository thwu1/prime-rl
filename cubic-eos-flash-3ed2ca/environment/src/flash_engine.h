#pragma once

#include "component_db.h"
#include <vector>
#include <string>

struct FlashResult {
    std::string problem_name;
    bool converged;
    bool two_phase;
    double V;          // Vapor fraction
    double Z_L, Z_V;   // Compressibility factors
    std::vector<double> x;         // Liquid mole fractions
    std::vector<double> y;         // Vapor mole fractions
    std::vector<double> ln_phi_L;  // Liquid-phase ln(fugacity coefficients)
    std::vector<double> ln_phi_V;  // Vapor-phase ln(fugacity coefficients)
};

// Phase stability via tangent-plane distance analysis.
// Returns true if the feed composition z is STABLE (single-phase).
bool check_stability(
    const std::vector<double>& z,
    const std::vector<double>& ai,
    const std::vector<double>& bi,
    const std::vector<int>& comp_idx,
    double T, double P);

// Perform isothermal flash at given (T, P) for feed composition z.
FlashResult run_flash(
    const std::string& name,
    const std::vector<int>& comp_idx,
    const std::vector<double>& z,
    double T, double P);
