
#include "kernels.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static double* periodic_pad(const double* x, int N) {
    double* p = (double*)malloc((N + 2) * sizeof(double));
    if (!p) return NULL;
    /* Vertex-centered: x[0] == x[N-1] under periodicity.
     * Left ghost  = x[N-2]  (second-to-last interior point)
     * Right ghost = x[1]    (second interior point) */
    p[0] = x[N - 2];
    memcpy(p + 1, x, N * sizeof(double));
    p[N + 1] = x[1];
    return p;
}

void compute_rhs(
    const double* Vx, const double* density, const double* pressure,
    double* drho_dt, double* dv_dt, double* dp_dt,
    int N, double dx, double eta, double zeta, double gamma,
    double art_visc
) {
    double* Vx_p   = periodic_pad(Vx, N);
    double* den_p  = periodic_pad(density, N);
    double* pres_p = periodic_pad(pressure, N);

    /* Mass flux = rho * v */
    double* mass_flux = (double*)malloc(N * sizeof(double));
    int i;
    for (i = 0; i < N; i++)
        mass_flux[i] = density[i] * Vx[i];
    double* mf_p = periodic_pad(mass_flux, N);

    double inv_2dx = 1.0 / (2.0 * dx);
    double inv_dx2 = 1.0 / (dx * dx);
    double visc_coeff = eta + zeta + eta / 3.0;
    double stress_coeff = zeta + 4.0 * eta / 3.0;
    double gm1 = gamma - 1.0;

    /* First derivative of velocity (needed for energy flux & art. visc.) */
    double* dv_dx = (double*)malloc(N * sizeof(double));
    for (i = 0; i < N; i++)
        dv_dx[i] = (Vx_p[i + 2] - Vx_p[i]) * inv_2dx;

    /* ── 1. Continuity: drho/dt = -d(rho*v)/dx ── */
    for (i = 0; i < N; i++)
        drho_dt[i] = -(mf_p[i + 2] - mf_p[i]) * inv_2dx;

    /* ── 2. Momentum ── */
    for (i = 0; i < N; i++) {
        double d2v = (Vx_p[i + 2] - 2.0 * Vx[i] + Vx_p[i]) * inv_dx2;
        double pgrad = (pres_p[i + 2] - pres_p[i]) * inv_2dx;
        double safe_den = density[i] > 1e-4 ? density[i] : 1e-4;

        double acc = -Vx[i] * dv_dx[i]
                     - pgrad / safe_den
                     + visc_coeff * d2v;

        /* Artificial viscosity: C * rho * dx^2 * |div_v| * div_v */
        double div_v = dv_dx[i];
        acc += art_visc * density[i] * dx * dx * fabs(div_v) * div_v;

        if (acc >  100.0) acc =  100.0;
        if (acc < -100.0) acc = -100.0;
        dv_dt[i] = acc;
    }

    /* ── 3. Energy -> pressure ── */
    double* eflux = (double*)malloc(N * sizeof(double));
    for (i = 0; i < N; i++) {
        double E = pressure[i] / gm1 + 0.5 * density[i] * Vx[i] * Vx[i];
        eflux[i] = (E + pressure[i]) * Vx[i]
                   - Vx[i] * stress_coeff * dv_dx[i];
    }
    double* ef_p = periodic_pad(eflux, N);

    for (i = 0; i < N; i++) {
        double dE_dt = -(ef_p[i + 2] - ef_p[i]) * inv_2dx;
        double kin = Vx[i] * density[i] * dv_dt[i]
                   + 0.5 * Vx[i] * Vx[i] * drho_dt[i];
        double dp = gm1 * (dE_dt - kin);
        double lim = 100.0 * pressure[i];
        if (dp >  lim) dp =  lim;
        if (dp < -lim) dp = -lim;
        dp_dt[i] = dp;
    }

    free(Vx_p); free(den_p); free(pres_p);
    free(mass_flux); free(mf_p);
    free(dv_dx); free(eflux); free(ef_p);
}

void euler_step(
    double* Vx, double* density, double* pressure,
    const double* drho_dt, const double* dv_dt, const double* dp_dt,
    int N, double dt
) {
    int i;
    for (i = 0; i < N; i++) {
        Vx[i] += dt * dv_dt[i];

        double d = density[i] + dt * drho_dt[i];
        if (d < 1e-4)  d = 1e-4;
        if (d > 1e5)   d = 1e5;
        density[i] = d;

        double p = pressure[i] + dt * dp_dt[i];
        if (p < 1e-4)  p = 1e-4;
        if (p > 1e5)   p = 1e5;
        pressure[i] = p;
    }
}

double compute_cfl_timestep(
    const double* Vx, const double* density, const double* pressure,
    int N, double dx, double gamma, double safety,
    double min_dt, double max_dt, double remaining
) {
    double mw = 0.0;
    int i;
    for (i = 0; i < N; i++) {
        double sd = density[i] > 1e-4 ? density[i] : 1e-4;
        double cs = sqrt(gamma * pressure[i] / sd);
        double w = fabs(Vx[i]) + cs;
        if (w > mw) mw = w;
    }
    double dt = safety * dx / (mw + 1e-6);
    if (dt > remaining) dt = remaining;
    if (dt > max_dt)    dt = max_dt;
    if (dt < min_dt)    dt = min_dt;
    return dt;
}

int has_nan(const double* arr, int N) {
    int i;
    for (i = 0; i < N; i++) {
        if (isnan(arr[i])) return 1;
    }
    return 0;
}
