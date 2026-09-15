/* N-body gravitational force computation using OpenMP */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <omp.h>

#define NBODIES 500
#define SOFTENING 1e-9

static unsigned int _lcg_state = 12345;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
}

typedef struct {
    double x, y, z;
    double mass;
} Body;

void compute_forces(Body *bodies, int n, double *fx, double *fy, double *fz) {
    memset(fx, 0, n * sizeof(double));
    memset(fy, 0, n * sizeof(double));
    memset(fz, 0, n * sizeof(double));

    /* Use Newton's third law: compute each pair once and update both bodies */
    #pragma omp parallel for schedule(dynamic, 16)
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            double dx = bodies[j].x - bodies[i].x;
            double dy = bodies[j].y - bodies[i].y;
            double dz = bodies[j].z - bodies[i].z;
            double dist_sq = dx*dx + dy*dy + dz*dz + SOFTENING;
            double inv_dist = 1.0 / sqrt(dist_sq);
            double inv_dist3 = inv_dist * inv_dist * inv_dist;
            double f = bodies[i].mass * bodies[j].mass * inv_dist3;

            double ffx = f * dx;
            double ffy = f * dy;
            double ffz = f * dz;

            fx[i] += ffx;
            fy[i] += ffy;
            fz[i] += ffz;

            fx[j] -= ffx;
            fy[j] -= ffy;
            fz[j] -= ffz;
        }
    }
}

int main(void) {
    Body *bodies = (Body *)malloc(NBODIES * sizeof(Body));
    double *fx = (double *)calloc(NBODIES, sizeof(double));
    double *fy = (double *)calloc(NBODIES, sizeof(double));
    double *fz = (double *)calloc(NBODIES, sizeof(double));

    for (int i = 0; i < NBODIES; i++) {
        bodies[i].x = lcg_rand_double() * 100.0;
        bodies[i].y = lcg_rand_double() * 100.0;
        bodies[i].z = lcg_rand_double() * 100.0;
        bodies[i].mass = lcg_rand_double() * 10.0 + 1.0;
    }

    omp_set_num_threads(4);
    compute_forces(bodies, NBODIES, fx, fy, fz);

    double sum_fx = 0, sum_fy = 0, sum_fz = 0;
    for (int i = 0; i < NBODIES; i++) {
        sum_fx += fx[i];
        sum_fy += fy[i];
        sum_fz += fz[i];
    }

    printf("sum_fx=%.10e\n", sum_fx);
    printf("sum_fy=%.10e\n", sum_fy);
    printf("sum_fz=%.10e\n", sum_fz);
    printf("fx[0]=%.10e\n", fx[0]);
    printf("fy[100]=%.10e\n", fy[100]);
    printf("fz[499]=%.10e\n", fz[NBODIES-1]);

    free(bodies);
    free(fx);
    free(fy);
    free(fz);
    return 0;
}
