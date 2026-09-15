#ifndef FLOWCORE_H
#define FLOWCORE_H

/* Tap type constants */
#define TAP_CORNER 0
#define TAP_FLANGE 1
#define TAP_D      2

/*
 * Orifice plate discharge coefficient (Reader-Harris/Gallagher).
 * D: pipe inner diameter [m]
 * Do: orifice diameter [m]
 * rho: fluid density [kg/m^3]
 * mu: dynamic viscosity [Pa*s]
 * m: mass flow rate [kg/s]
 * taps: TAP_CORNER, TAP_FLANGE, or TAP_D
 * Returns: discharge coefficient [-]
 */
double orifice_C(double D, double Do, double rho, double mu, double m, int taps);

/*
 * Orifice expansibility factor.
 * D: pipe inner diameter [m]
 * Do: orifice diameter [m]
 * P1: upstream absolute pressure [Pa]
 * P2: downstream absolute pressure [Pa]
 * k: isentropic exponent [-]
 * Returns: expansibility factor [-]
 */
double orifice_eps(double D, double Do, double P1, double P2, double k);

/*
 * Iterative orifice mass flow rate solver.
 * D: pipe inner diameter [m]
 * Do: orifice diameter [m]
 * P1: upstream absolute pressure [Pa]
 * P2: downstream absolute pressure [Pa]
 * rho: fluid density [kg/m^3]
 * mu: dynamic viscosity [Pa*s]
 * k: isentropic exponent [-]
 * taps: TAP_CORNER, TAP_FLANGE, or TAP_D
 * Returns: mass flow rate [kg/s]
 */
double orifice_flow(double D, double Do, double P1, double P2,
                    double rho, double mu, double k, int taps);

#endif /* FLOWCORE_H */
