
#include "kernels.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

/*
 * Helper: create a periodically padded copy of x (length N) -> length N+2.
 *
 * For a vertex-centered grid where x[0] and x[N-1] are the same physical
 * point (periodic boundary), the ghost cells must come from interior points:
 *   padded[0]     = ???   (left ghost from interior)
 *   padded[1..N]  = x[0..N-1]
 *   padded[N+1]   = ???   (right ghost from interior)
 *
 * Caller must free() the returned pointer.
 */
static double* periodic_pad(const double* x, int N) {
    double* p = (double*)malloc((N + 2) * sizeof(double));
    if (!p) return NULL;
    memcpy(p + 1, x, N * sizeof(double));
    /* TODO: set correct ghost cell values for vertex-centered periodic grid */
    p[0] = 0.0;       /* placeholder — wrong value */
    p[N + 1] = 0.0;   /* placeholder — wrong value */
    return p;
}

void compute_rhs(
    const double* Vx, const double* density, const double* pressure,
    double* drho_dt, double* dv_dt, double* dp_dt,
    int N, double dx, double eta, double zeta, double gamma,
    double art_visc
) {
    /*
     * TODO: Implement the full RHS of the 1D compressible Navier-Stokes
     * equations using central finite differences.
     *
     * 1. Periodically pad all field arrays
     * 2. Compute first derivative dv/dx and second derivative d2v/dx2
     * 3. Continuity:  drho/dt = -d(rho*v)/dx
     * 4. Momentum:    dv/dt = -v*dv/dx - (1/rho)*dp/dx
     *                       + (eta + zeta + eta/3) * d2v/dx2
     *                       + artificial_viscosity_term
     * 5. Energy:      compute total energy E = p/(gamma-1) + rho*v^2/2,
     *                 energy flux = (E + p)*v - v*(zeta + 4*eta/3)*dv/dx,
     *                 then dp/dt = (gamma-1) * (dE/dt - kinetic_change)
     *
     * Remember to free all malloc'd memory before returning.
     */
    (void)Vx; (void)density; (void)pressure;
    (void)dx; (void)eta; (void)zeta; (void)gamma; (void)art_visc;
    memset(drho_dt, 0, N * sizeof(double));
    memset(dv_dt, 0, N * sizeof(double));
    memset(dp_dt, 0, N * sizeof(double));
}

void euler_step(
    double* Vx, double* density, double* pressure,
    const double* drho_dt, const double* dv_dt, const double* dp_dt,
    int N, double dt
) {
    /*
     * TODO: Forward Euler update for all three fields.
     * field_new = field + dt * d_field_dt
     * Clip density to [1e-4, 1e5] and pressure to [1e-4, 1e5].
     */
    (void)Vx; (void)density; (void)pressure;
    (void)drho_dt; (void)dv_dt; (void)dp_dt;
    (void)N; (void)dt;
}

double compute_cfl_timestep(
    const double* Vx, const double* density, const double* pressure,
    int N, double dx, double gamma, double safety,
    double min_dt, double max_dt, double remaining
) {
    /*
     * TODO: CFL-based adaptive timestep.
     * 1. For each grid point, compute sound speed c_s = sqrt(gamma * p / rho)
     * 2. Find maximum wave speed: max(|v| + c_s) over all grid points
     * 3. Hyperbolic CFL limit: safety * dx / (max_wave_speed + epsilon)
     * 4. Return min(cfl_dt, remaining, max_dt), clamped below by min_dt
     */
    (void)Vx; (void)density; (void)pressure;
    (void)N; (void)dx; (void)gamma; (void)safety;
    (void)max_dt; (void)remaining;
    return min_dt;
}

int has_nan(const double* arr, int N) {
    for (int i = 0; i < N; i++) {
        if (isnan(arr[i])) return 1;
    }
    return 0;
}
