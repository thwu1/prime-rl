#ifndef THERMAL_MODEL_H
#define THERMAL_MODEL_H

/*
 * Incomplete Thermal Model Simulator
 *
 * Models a single thermal mass (the pot) receiving external heat input
 * Q_in(t) and losing heat to the environment through air convection.
 *
 * Governing equation:
 *   C2 * dT/dt = Q_in(t) - G_air * (T - T_env)
 *
 * where Q_in(t) = (1 + sin(0.005 * t^2)) / 2
 *
 * This model is known to be incomplete -- it does not accurately
 * reproduce measured temperature dynamics from the real system.
 */

/*
 * Simulate the incomplete thermal model using RK4 integration.
 *
 * Args:
 *   t_eval  - array of time points (seconds)
 *   n       - number of time points
 *   C2      - thermal capacity [J/K]
 *   G_air   - convective conductance to environment [W/K]
 *   T_env   - environment temperature [K]
 *   T0      - initial temperature [K]
 *   T_out   - pre-allocated output array of size n (temperatures in K)
 *
 * Returns: 0 on success, -1 on invalid input
 */
int thermal_simulate(const double* t_eval, int n,
                     double C2, double G_air, double T_env, double T0,
                     double* T_out);

/* Return heat input Q_in at time t (watts). */
double get_input_heat(double t);

/* Return dT/dt from the incomplete model at a single state point. */
double model_residual(double t, double T, double C2, double G_air, double T_env);

#endif
