
#ifndef CNS_KERNELS_H
#define CNS_KERNELS_H

/*
 * C kernels for the 1D compressible Navier-Stokes solver.
 *
 * All functions operate on a single spatial sample of length N.
 * The grid is vertex-centered on [-1, 1] with dx = 2/(N-1).
 * Periodic boundary conditions: grid endpoints coincide, so ghost
 * cells must come from interior points (not the coincident endpoints).
 */

/*
 * Compute the RHS of all three conservation equations.
 *
 * Inputs:
 *   Vx       - velocity array [N]
 *   density  - density array [N]
 *   pressure - pressure array [N]
 *   N        - number of grid points
 *   dx       - grid spacing = 2/(N-1)
 *   eta      - shear viscosity coefficient
 *   zeta     - bulk viscosity coefficient
 *   gamma    - ratio of specific heats (5/3 for monatomic ideal gas)
 *   art_visc - artificial viscosity coefficient for stability
 *
 * Outputs (pre-allocated, length N each):
 *   drho_dt  - time derivative of density
 *   dv_dt    - time derivative of velocity (clipped to [-100, 100])
 *   dp_dt    - time derivative of pressure (clipped relative to local pressure)
 */
void compute_rhs(
    const double* Vx, const double* density, const double* pressure,
    double* drho_dt, double* dv_dt, double* dp_dt,
    int N, double dx, double eta, double zeta, double gamma,
    double art_visc
);

/*
 * Forward Euler update with density/pressure clipping.
 * Updates Vx, density, pressure arrays in-place.
 * Density and pressure are clipped to [1e-4, 1e5].
 */
void euler_step(
    double* Vx, double* density, double* pressure,
    const double* drho_dt, const double* dv_dt, const double* dp_dt,
    int N, double dt
);

/*
 * Compute CFL-based adaptive timestep.
 * Returns min(safety * dx / max_wave_speed, remaining, max_dt),
 * clamped below by min_dt.
 *
 * max_wave_speed = max_i(|Vx[i]| + c_s[i])
 * where c_s = sqrt(gamma * pressure / density) is the sound speed.
 */
double compute_cfl_timestep(
    const double* Vx, const double* density, const double* pressure,
    int N, double dx, double gamma, double safety,
    double min_dt, double max_dt, double remaining
);

/*
 * Check for NaN values in array. Returns 1 if any NaN found, 0 otherwise.
 */
int has_nan(const double* arr, int N);

#endif /* CNS_KERNELS_H */
