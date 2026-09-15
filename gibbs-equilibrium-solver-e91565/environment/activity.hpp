#pragma once
// Activity coefficient models for aqueous geochemistry
//

// B-dot extended Debye-Huckel activity coefficient
// log10(gamma) = -A(T)*z^2*sqrt(I)/(1 + a_i*B(T)*sqrt(I)) + bdot(T)*I
// Returns log10(gamma). For neutral species (z=0), returns 0.
double bdot_log10_gamma(int z, double ion_size_a, double I, double T);

// Debye-Huckel A parameter at temperature T (Kelvin)
double debye_huckel_A(double T);

// Debye-Huckel B parameter at temperature T (Kelvin)
double debye_huckel_B(double T);

// B-dot parameter at temperature T (Kelvin)
double bdot_param(double T);

// Ionic strength from full species molality array
double compute_ionic_strength(const double mol[], const int charges[], int n);
