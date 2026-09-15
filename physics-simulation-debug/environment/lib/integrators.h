#ifndef INTEGRATORS_H
#define INTEGRATORS_H

/*
 * Numerical integration routines for physics simulations.
 */

/* Acceleration callback: accel(pos, acc_out, dim, params) */
typedef void (*accel_fn)(const double *pos, double *acc_out, int dim,
                         const void *params);

/* Velocity-Verlet (leapfrog) integrator step for Hamiltonian systems.
 * pos: position vector [dim], updated in-place
 * vel: velocity vector [dim], updated in-place
 * dt: time step
 * dim: number of spatial dimensions
 * accel: acceleration callback
 * params: opaque pointer forwarded to accel
 */
void verlet_step(double *pos, double *vel, double dt, int dim,
                 accel_fn accel, const void *params);

/* Forward-Time Central-Space (FTCS) diffusion stencil.
 * u:     input field [n]
 * u_new: output field [n]
 * n:     number of grid points
 * r:     CFL number  (alpha * dt / dx^2)
 */
void ftcs_step(const double *u, double *u_new, int n, double r);

#endif
