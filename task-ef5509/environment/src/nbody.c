/*
 * Parallel N-body gravitational simulation using OpenMP.
 * Computes pairwise gravitational forces and updates particle positions.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <omp.h>

#define NUM_PARTICLES 200
#define NUM_STEPS 10
#define DT 0.01
#define SOFTENING 1e-9

int main() {
    double *x  = (double *)malloc(NUM_PARTICLES * sizeof(double));
    double *y  = (double *)malloc(NUM_PARTICLES * sizeof(double));
    double *z  = (double *)malloc(NUM_PARTICLES * sizeof(double));
    double *vx = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *vy = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *vz = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *fx = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *fy = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *fz = (double *)calloc(NUM_PARTICLES, sizeof(double));
    double *mass = (double *)malloc(NUM_PARTICLES * sizeof(double));

    srand(42);
    for (int i = 0; i < NUM_PARTICLES; i++) {
        x[i] = (double)rand() / RAND_MAX;
        y[i] = (double)rand() / RAND_MAX;
        z[i] = (double)rand() / RAND_MAX;
        mass[i] = 1.0;
    }

    for (int step = 0; step < NUM_STEPS; step++) {
        for (int i = 0; i < NUM_PARTICLES; i++)
            fx[i] = fy[i] = fz[i] = 0.0;

        /* Compute forces using Newton's third law optimization:
         * for each pair (i,j) with j > i, compute the force once
         * and apply it to both particles. */
        #pragma omp parallel for schedule(dynamic)
        for (int i = 0; i < NUM_PARTICLES; i++) {
            for (int j = i + 1; j < NUM_PARTICLES; j++) {
                double dx = x[j] - x[i];
                double dy = y[j] - y[i];
                double dz = z[j] - z[i];
                double r = sqrt(dx * dx + dy * dy + dz * dz + SOFTENING);
                double f = mass[i] * mass[j] / (r * r * r);
                double fdx = f * dx, fdy = f * dy, fdz = f * dz;

                fx[i] += fdx;  fy[i] += fdy;  fz[i] += fdz;
                fx[j] -= fdx;  fy[j] -= fdy;  fz[j] -= fdz;
            }
        }

        for (int i = 0; i < NUM_PARTICLES; i++) {
            vx[i] += fx[i] * DT;
            vy[i] += fy[i] * DT;
            vz[i] += fz[i] * DT;
            x[i] += vx[i] * DT;
            y[i] += vy[i] * DT;
            z[i] += vz[i] * DT;
        }
    }

    double ke = 0.0;
    for (int i = 0; i < NUM_PARTICLES; i++)
        ke += 0.5 * mass[i] * (vx[i]*vx[i] + vy[i]*vy[i] + vz[i]*vz[i]);
    printf("%.10f\n", ke);

    free(x); free(y); free(z);
    free(vx); free(vy); free(vz);
    free(fx); free(fy); free(fz);
    free(mass);
    return 0;
}
