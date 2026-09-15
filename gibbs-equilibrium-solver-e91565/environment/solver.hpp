#pragma once
#include "thermo.hpp"


struct Problem {
    double T;           // temperature (K)
    double total_Na;    // mol/kgw
    double total_Cl;
    double total_Ca;
    double total_C;
    double total_S;
};

struct Result {
    double pH;
    double ionic_strength;
    double m[NUM_SPECIES];
    double charge_balance;
    double calcite_SI;
    double gypsum_SI;
    double n_calcite;    // mol precipitated per kgw
    double n_gypsum;
    bool   converged;
    int    iterations;
};

Result solve(const Problem& p);
