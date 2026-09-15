 *
 * Incomplete thermal model simulator.
 * Models a single thermal mass receiving external heat and losing
 * heat to the environment. This model is known to be incomplete.
 */

#include <math.h>
#include <stdlib.h>

static double input_heat(double t) {
    return (1.0 + sin(0.005 * t * t)) / 2.0;
}

int thermal_simulate(const double* t_eval, int n,
                     double C2, double G_air, double T_env, double T0,
                     double* T_out) {
    if (n <= 0 || !t_eval || !T_out) return -1;

    T_out[0] = T0;

    for (int i = 0; i < n - 1; i++) {
        double dt = t_eval[i + 1] - t_eval[i];
        double t = t_eval[i];
        double T = T_out[i];

        /* RK4 integration of: C2 * dT/dt = Q_in(t) - G_air*(T - T_env) */
        double k1 = (input_heat(t) - G_air * (T - T_env)) / C2;
        double k2 = (input_heat(t + dt/2) - G_air * (T + dt/2*k1 - T_env)) / C2;
        double k3 = (input_heat(t + dt/2) - G_air * (T + dt/2*k2 - T_env)) / C2;
        double k4 = (input_heat(t + dt) - G_air * (T + dt*k3 - T_env)) / C2;

        T_out[i + 1] = T + (dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4);
    }

    return 0;
}

double get_input_heat(double t) {
    return input_heat(t);
}

double model_residual(double t, double T, double C2, double G_air, double T_env) {
    return (input_heat(t) - G_air * (T - T_env)) / C2;
}
