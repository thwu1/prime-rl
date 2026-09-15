#pragma once
// Thermodynamic constants and species definitions for aqueous geochemistry
// H2O-Na-Cl-Ca-C-S system with temperature-dependent equilibria
//

#include <cmath>
#include <algorithm>

constexpr double R_GAS = 8.314462;       // J/(mol K)
constexpr double LN10  = 2.302585093;

// ---- Species indices --------------------------------------------------------
enum Species {
    SP_H = 0, SP_OH, SP_NA, SP_CL, SP_CA, SP_SO4,
    SP_CO2, SP_HCO3, SP_CO3, SP_CACO3AQ, SP_NACLAQ, SP_CASO4AQ,
    NUM_SPECIES
};

// Ionic charges
static const int CHARGE[NUM_SPECIES] = {
     1, -1,  1, -1,  2, -2,   // H+  OH-  Na+  Cl-  Ca2+  SO42-
     0, -1, -2,  0,  0,  0    // CO2 HCO3- CO32- CaCO3aq NaClaq CaSO4aq
};

// Ion-size parameters (angstroms) for B-dot extended Debye-Huckel
static const double ION_SIZE[NUM_SPECIES] = {
    9.0, 3.5, 4.0, 3.5, 6.0, 5.0,   // H+  OH-  Na+  Cl-  Ca2+  SO42-
    0.0, 5.4, 5.4, 0.0, 0.0, 0.0    // CO2 HCO3- CO32- CaCO3aq NaClaq CaSO4aq
};

// ---- Basis (primary) species ------------------------------------------------
enum Primary {
    PR_H = 0, PR_NA, PR_CL, PR_CA, PR_CO2, PR_SO4,
    NUM_PRIMARY
};

// ---- Reaction indices -------------------------------------------------------
enum Reaction {
    RX_WATER = 0,  // H2O        = H+  + OH-
    RX_A1,         // CO2 + H2O  = H+  + HCO3-
    RX_A2,         // HCO3-      = H+  + CO3--
    RX_CACO3,      // Ca++ + CO3-- = CaCO3(aq)
    RX_NACL,       // Na+  + Cl-   = NaCl(aq)
    RX_CASO4,      // Ca++ + SO4-- = CaSO4(aq)
    NUM_REACTIONS
};

// ---- Mineral indices --------------------------------------------------------
enum Mineral {
    MIN_CALCITE = 0,  // CaCO3(s)      = Ca++ + CO3--
    MIN_GYPSUM,       // CaSO4:2H2O(s) = Ca++ + SO4-- + 2H2O
    NUM_MINERALS
};

static const int MAX_UNKNOWNS = NUM_PRIMARY + NUM_MINERALS;  // 8

// ---- Thermodynamic data -----------------------------------------------------
// log_K at 25 C and delta_H (J/mol) for van't Hoff extrapolation:
//   log_K(T) = log_K(25) + delta_H / (2.303 * R) * (1/298.15 - 1/T)
struct ThermoRx {
    double log_k_25;
    double delta_h;   // J/mol

    inline double log_k(double T) const {
        if (std::abs(T - 298.15) < 0.01) return log_k_25;
        // Van't Hoff extrapolation
        return log_k_25 + delta_h / (R_GAS) * (1.0 / 298.15 - 1.0 / T);
    }
};

// Aqueous reaction data (SUPCRT / PHREEQC phreeqc.dat)
static const ThermoRx RXDATA[NUM_REACTIONS] = {
    {-13.991,  55815.0},   // H2O dissociation
    { -6.343,   7646.0},   // CO2 first dissociation
    {-10.326,  14899.0},   // HCO3- second dissociation
    {  3.326, -29000.0},   // CaCO3(aq) complexation
    { -0.777,   4000.0},   // NaCl(aq) ion pairing
    {  2.309,   7100.0},   // CaSO4(aq) complexation
};

// Mineral dissolution data
static const ThermoRx MINDATA[NUM_MINERALS] = {
    {-8.478, -9613.0},    // Calcite dissolution
    {-4.581,  -690.0},    // Gypsum dissolution
};
