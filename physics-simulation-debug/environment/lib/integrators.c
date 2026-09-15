/*
 * Numerical integration library for physics simulation pipeline.
 */
#include "integrators.h"
#include <stdlib.h>

void verlet_step(double *pos, double *vel, double dt, int dim,
                 accel_fn accel, const void *params) {
    int i;
    double *acc_old = (double *)calloc(dim, sizeof(double));
    double *acc_new = (double *)calloc(dim, sizeof(double));

    /* acceleration at current position */
    accel(pos, acc_old, dim, params);

    /* position full-step:  x += v*dt + 0.5*a*dt^2 */
    for (i = 0; i < dim; i++) {
        pos[i] += vel[i] * dt + 0.5 * acc_old[i] * dt * dt;
    }

    /* acceleration at new position */
    accel(pos, acc_new, dim, params);

    /* velocity full-step:  v += 0.5*(a_old + a_new)*dt */
    for (i = 0; i < dim; i++) {
        vel[i] += 0.5 * (acc_old[i] + acc_new[i]) * dt * dt;
    }

    free(acc_old);
    free(acc_new);
}

void ftcs_step(const double *u, double *u_new, int n, double r) {
    int i;
    u_new[0] = u[0];
    u_new[n - 1] = u[n - 1];
    for (i = 1; i < n - 1; i++) {
        u_new[i] = u[i] + r * (u[i + 1] - 2.0 * u[i] + u[i - 1]);
    }
}
