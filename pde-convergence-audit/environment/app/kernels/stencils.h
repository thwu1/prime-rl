#ifndef STENCILS_H
#define STENCILS_H

/* Thomas algorithm for tridiagonal systems.
 * a: lower diagonal (n elements, a[0] unused)
 * b: main diagonal (n elements)
 * c: upper diagonal (n elements, c[n-1] unused)
 * d: right-hand side (n elements)
 * x: output solution (n elements)
 */
void thomas_solve(int n, const double *a, const double *b,
                  const double *c, const double *d, double *x);

/* Single time step for periodic advection u_t + c*u_x = 0.
 * u: solution at current time (N elements, periodic)
 * u_new: output solution at next time (N elements)
 * N: number of grid points
 * nu: Courant number c*dt/h
 */
void lax_wendroff_step(const double *u, double *u_new, int N, double nu);

/* Compute RMS (L2) error between two arrays. */
double compute_rms_error(const double *u_num, const double *u_exact, int n);

#endif
