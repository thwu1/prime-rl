#pragma once

#include <string>
#include <vector>
#include <algorithm>

struct Component {
    std::string name;
    double Tc;    // Critical temperature [K]
    double Pc;    // Critical pressure [Pa]
    double omega; // Acentric factor [-]
};

// Standard component database indexed 0..9
inline const std::vector<Component> COMP_DB = {
    /* 0 */ {"Methane",   190.564,  4599200.0, 0.01142},
    /* 1 */ {"Ethane",    305.322,  4872200.0, 0.09952},
    /* 2 */ {"Propane",   369.830,  4251200.0, 0.15229},
    /* 3 */ {"n-Butane",  425.125,  3796000.0, 0.20081},
    /* 4 */ {"n-Pentane", 469.700,  3367500.0, 0.25137},
    /* 5 */ {"n-Hexane",  507.600,  3025000.0, 0.30131},
    /* 6 */ {"n-Decane",  617.700,  2110000.0, 0.49217},
    /* 7 */ {"Nitrogen",  126.192,  3395800.0, 0.03720},
    /* 8 */ {"CO2",       304.128,  7377300.0, 0.22520},
    /* 9 */ {"H2S",       373.100,  8962900.0, 0.09417},
};

// Symmetric binary interaction parameters kij = kji
inline double get_kij(int i, int j) {
    if (i == j) return 0.0;
    int lo = std::min(i, j), hi = std::max(i, j);
    // Methane(0) pairs
    if (lo == 0 && hi == 1) return 0.0026;   // CH4-C2H6
    if (lo == 0 && hi == 2) return 0.0140;   // CH4-C3H8
    if (lo == 0 && hi == 3) return 0.0133;   // CH4-nC4
    if (lo == 0 && hi == 4) return 0.0230;   // CH4-nC5
    if (lo == 0 && hi == 5) return 0.0300;   // CH4-nC6
    if (lo == 0 && hi == 6) return 0.0422;   // CH4-nC10
    if (lo == 0 && hi == 7) return 0.0311;   // CH4-N2
    if (lo == 0 && hi == 8) return 0.0919;   // CH4-CO2
    if (lo == 0 && hi == 9) return 0.0800;   // CH4-H2S
    // CO2(8) pairs
    if (lo == 1 && hi == 8) return 0.1300;   // C2-CO2
    if (lo == 2 && hi == 8) return 0.1250;   // C3-CO2
    if (lo == 8 && hi == 9) return 0.0974;   // CO2-H2S
    // N2(7) pairs
    if (lo == 1 && hi == 7) return 0.0515;   // C2-N2
    if (lo == 2 && hi == 7) return 0.0852;   // C3-N2
    return 0.0;
}
