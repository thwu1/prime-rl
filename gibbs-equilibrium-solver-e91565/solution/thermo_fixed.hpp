#pragma once
// FIXED thermodynamic constants — corrected van't Hoff formula
//

#include <cmath>
#include <algorithm>

constexpr double R_GAS = 8.314462;
constexpr double LN10  = 2.302585093;

enum Species {
    SP_H = 0, SP_OH, SP_NA, SP_CL, SP_CA, SP_SO4,
    SP_CO2, SP_HCO3, SP_CO3, SP_CACO3AQ, SP_NACLAQ, SP_CASO4AQ,
    NUM_SPECIES
};

static const int CHARGE[NUM_SPECIES] = {
     1, -1,  1, -1,  2, -2,
     0, -1, -2,  0,  0,  0
};

static const double ION_SIZE[NUM_SPECIES] = {
    9.0, 3.5, 4.0, 3.5, 6.0, 5.0,
    0.0, 5.4, 5.4, 0.0, 0.0, 0.0
};

enum Primary {
    PR_H = 0, PR_NA, PR_CL, PR_CA, PR_CO2, PR_SO4,
    NUM_PRIMARY
};

enum Reaction {
    RX_WATER = 0, RX_A1, RX_A2, RX_CACO3, RX_NACL, RX_CASO4,
    NUM_REACTIONS
};

enum Mineral {
    MIN_CALCITE = 0, MIN_GYPSUM,
    NUM_MINERALS
};

static const int MAX_UNKNOWNS = NUM_PRIMARY + NUM_MINERALS;

struct ThermoRx {
    double log_k_25;
    double delta_h;

    inline double log_k(double T) const {
        if (std::abs(T - 298.15) < 0.01) return log_k_25;
        // FIX: divide by (LN10 * R_GAS) for correct log10-scale van't Hoff
        return log_k_25 + delta_h / (LN10 * R_GAS) * (1.0 / 298.15 - 1.0 / T);
    }
};

static const ThermoRx RXDATA[NUM_REACTIONS] = {
    {-13.991,  55815.0},
    { -6.343,   7646.0},
    {-10.326,  14899.0},
    {  3.326, -29000.0},
    { -0.777,   4000.0},
    {  2.309,   7100.0},
};

static const ThermoRx MINDATA[NUM_MINERALS] = {
    {-8.478, -9613.0},
    {-4.581,  -690.0},
};
